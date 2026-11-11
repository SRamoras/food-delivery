-- EXPLAIN evidence for frequent query 4 (docs/postgres.md), run as the superuser on the
-- seeded data. The query runs without its index (dropped inside a transaction that is
-- rolled back, so nothing changes) and then with it.
-- Usage: psql -v courier=<id> -f postgres/sql/explain_deliveries.sql

-- Query 4: a courier's active deliveries (the same filter as the rule 3 count in F4).
BEGIN;
DROP INDEX ix_deliveries_courier_active;
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, accepted_at, picked_up_at
  FROM deliveries WHERE courier_id = :courier AND delivered_at IS NULL;
ROLLBACK;

EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, accepted_at, picked_up_at
  FROM deliveries WHERE courier_id = :courier AND delivered_at IS NULL;
