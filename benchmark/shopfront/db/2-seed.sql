INSERT INTO products (id, name, price, inventory)
SELECT i, 'Product ' || i, (i * 10) % 1000 + 100, 10000
FROM generate_series(1, 5000) i;

INSERT INTO orders (id, product_id, quantity, status, customer_email, idempotency_key)
SELECT i, (i % 5000) + 1, 1,
       CASE WHEN i % 10 = 0 THEN 'PENDING' ELSE 'COMPLETED' END,
       'user' || (i % 1000) || '@example.com',
       'idem-' || i
FROM generate_series(1, 20000) i;

SELECT setval('products_id_seq', 5000);
SELECT setval('orders_id_seq', 20000);
