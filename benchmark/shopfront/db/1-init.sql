CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price INTEGER NOT NULL,
    inventory INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    status VARCHAR(50) NOT NULL,
    customer_email VARCHAR(255) NOT NULL,
    idempotency_key VARCHAR(255) UNIQUE
);

CREATE INDEX idx_orders_customer_email ON orders(customer_email);

CREATE TABLE jobs (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    type VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL
);
