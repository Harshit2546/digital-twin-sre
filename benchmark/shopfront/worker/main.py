import os
import yaml
import time
import logging
from psycopg_pool import ConnectionPool

with open(os.getenv('APP_CONFIG', '/app/config/app.yaml')) as f:
    config = yaml.safe_load(f)

logger = logging.getLogger("worker")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('{"timestamp": "%(asctime)s", "level": "%(levelname)s", "request_id": "%(process)d", "message": "%(message)s"}')
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

os.makedirs('/app/logs', exist_ok=True)
fh = logging.FileHandler('/app/logs/worker.log')
fh.setFormatter(formatter)
logger.addHandler(fh)

pool = ConnectionPool(conninfo=os.getenv('DB_URL'), min_size=2, max_size=5, timeout=0.5)

def process_jobs():
    while True:
        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, order_id, type FROM jobs WHERE status = 'PENDING' LIMIT 1 FOR UPDATE SKIP LOCKED")
                    job = cur.fetchone()
                    if job:
                        logger.info(f"Processing job {job[0]} of type {job[2]} for order {job[1]}")
                        time.sleep(0.05)
                        cur.execute("UPDATE jobs SET status = 'COMPLETED' WHERE id = %s", (job[0],))
                        conn.commit()
                    else:
                        time.sleep(0.5)
        except Exception as e:
            logger.error(f"Worker error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    logger.info("Worker started")
    process_jobs()
