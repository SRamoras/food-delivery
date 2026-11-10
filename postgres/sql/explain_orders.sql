-- EXPLAIN evidence for frequent queries 2 and 3 (docs/postgres.md), run as the superuser
-- on the seeded data. Each query runs without its index (dropped inside a transaction
-- that is rolled back, so nothing changes) and then with it.
-- Usage: psql -v customer=<id> -v restaurant=<id> -f postgres/sql/explain_orders.sql

-- Query 2: the orders of a customer, newest first, 20 per page.
BEGIN;
DROP INDEX ix_orders_customer_id_created_at;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, restaurant_id, status, total, created_at
  FROM orders WHERE customer_id = :customer
 ORDER BY created_at DESC LIMIT 20;
ROLLBACK;

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, restaurant_id, status, total, created_at
  FROM orders WHERE customer_id = :customer
 ORDER BY created_at DESC LIMIT 20;

-- Query 3: the orders of a restaurant in accepted, preparing or ready (kitchen screen).
BEGIN;
DROP INDEX ix_orders_restaurant_active;
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, status, created_at
  FROM orders
 WHERE restaurant_id = :restaurant AND status IN ('accepted', 'preparing', 'ready')
 ORDER BY created_at;
ROLLBACK;

EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, status, created_at
  FROM orders
 WHERE restaurant_id = :restaurant AND status IN ('accepted', 'preparing', 'ready')
 ORDER BY created_at;
