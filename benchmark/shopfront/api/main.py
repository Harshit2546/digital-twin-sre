import os
import yaml
import logging
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Optional, Dict, Any
import psycopg
from psycopg_pool import ConnectionPool
import httpx
import time

app = FastAPI()

with open(os.getenv('APP_CONFIG', '/app/config/app.yaml')) as f:
    config = yaml.safe_load(f)

# Logging setup
logger = logging.getLogger("api")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('{"timestamp": "%(asctime)s", "level": "%(levelname)s", "request_id": "%(process)d", "message": "%(message)s"}')
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

os.makedirs('/app/logs', exist_ok=True)
fh = logging.FileHandler('/app/logs/api.log')
fh.setFormatter(formatter)
logger.addHandler(fh)

pool = ConnectionPool(
    conninfo=os.getenv('DB_URL'),
    min_size=config['db']['pool_size'],
    max_size=config['db']['pool_size'],
    timeout=0.5
)

product_cache = {}

metrics = {
    "request_count": 0,
    "error_count": 0,
    "latencies": [],
    "status_counts": {}
}

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    path = request.url.path
    if path not in metrics["status_counts"]:
        metrics["status_counts"][path] = {}
        
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as e:
        status = 500
        raise e
    finally:
        metrics["request_count"] += 1
        if status >= 500:
            metrics["error_count"] += 1
        latency = time.time() - start
        metrics["latencies"].append(latency)
        if len(metrics["latencies"]) > 2000:
            metrics["latencies"] = metrics["latencies"][-2000:]
        metrics["status_counts"][path][status] = metrics["status_counts"][path].get(status, 0) + 1
    return response

class OrderRequest(BaseModel):
    product_id: int
    quantity: int
    customer_email: str
    idempotency_key: str

class PriceRequest(BaseModel):
    price: int

@app.get("/health")
def health():
    logger.warning("Red herring warning: memory usage is slightly elevated.")
    return {"status": "ok"}

@app.get("/metrics")
def get_metrics():
    latencies = sorted(metrics["latencies"])
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    return {
        "request_count": metrics["request_count"],
        "error_count": metrics["error_count"],
        "p95_latency": p95,
        "status_counts": metrics["status_counts"]
    }

@app.post("/metrics/reset")
def reset_metrics():
    metrics["request_count"] = 0
    metrics["error_count"] = 0
    metrics["latencies"] = []
    metrics["status_counts"] = {}
    return {"status": "ok"}

@app.get("/products")
def list_products():
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, price, inventory FROM products LIMIT 100")
            return [{"id": r[0], "name": r[1], "price": r[2], "inventory": r[3]} for r in cur.fetchall()]

@app.get("/products/{id}")
def get_product(id: int):
    if id in product_cache:
        return product_cache[id]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, price, inventory FROM products WHERE id = %s", (id,))
            r = cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Product not found")
            price = r[2]
            if config.get("features", {}).get("enable_new_discount", False):
                price = int(price * 0.9)
            prod = {"id": r[0], "name": r[1], "price": price, "inventory": r[3]}
            if len(product_cache) < config.get("cache", {}).get("max_size", 1000):
                product_cache[id] = prod
            return prod

@app.post("/products/{id}/price")
def update_price(id: int, request: PriceRequest):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE products SET price = %s WHERE id = %s RETURNING id", (request.price, id))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Product not found")
            conn.commit()
    if id in product_cache:
        del product_cache[id]
    return {"status": "ok"}

@app.get("/orders/{id}")
def get_order(id: int):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, product_id, quantity, status FROM orders WHERE id = %s", (id,))
            r = cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Order not found")
            return {"id": r[0], "product_id": r[1], "quantity": r[2], "status": r[3].lower() if r[3] else None}

@app.post("/orders")
def create_order(order: OrderRequest, request: Request):
    logger.info(f"Received order for product {order.product_id} from {order.customer_email}")
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM orders WHERE idempotency_key = %s", (order.idempotency_key,))
            existing = cur.fetchone()
            if existing:
                return {"order_id": existing[0], "status": "COMPLETED"}

            cur.execute("SELECT id, price, inventory FROM products WHERE id = %s", (order.product_id,))
            r = cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail="Product not found")
            
            if r[2] < order.quantity:
                raise HTTPException(status_code=400, detail="Not enough inventory")

            payments_url = os.getenv('PAYMENTS_URL')
            headers = {"api-key": os.getenv("API_KEY", "default")}
            
            amount = r[1] * order.quantity
            max_attempts = config['payments']['retry']['max_attempts']
            backoff = config['payments']['retry']['backoff']
            timeout = config['payments'].get('timeout', 5.0)
            
            for attempt in range(max_attempts):
                try:
                    resp = httpx.post(f"{payments_url}/charge", json={"amount": amount}, headers=headers, timeout=timeout)
                    resp.raise_for_status()
                    break
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise HTTPException(status_code=502, detail="Payment failed")
                    time.sleep(backoff)

            cur.execute(
                "INSERT INTO orders (product_id, quantity, status, customer_email, idempotency_key) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (order.product_id, order.quantity, 'COMPLETED', order.customer_email, order.idempotency_key)
            )
            order_id = cur.fetchone()[0]
            
            cur.execute("UPDATE products SET inventory = inventory - %s WHERE id = %s", (order.quantity, order.product_id))
            cur.execute("INSERT INTO jobs (order_id, type, status) VALUES (%s, %s, %s)", (order_id, 'email', 'PENDING'))
            conn.commit()
            return {"order_id": order_id, "status": "COMPLETED"}

@app.get("/orders")
def get_orders_by_email(customer_email: str):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, product_id, quantity, status FROM orders WHERE customer_email = %s LIMIT 50", (customer_email,))
            return [{"id": r[0], "product_id": r[1], "quantity": r[2], "status": r[3]} for r in cur.fetchall()]

@app.get("/orders/count/{idempotency_key}")
def count_orders(idempotency_key: str):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM orders WHERE idempotency_key = %s", (idempotency_key,))
            return {"count": cur.fetchone()[0]}
