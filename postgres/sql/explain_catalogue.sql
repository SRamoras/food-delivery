-- EXPLAIN evidence for frequent query 1 (docs/postgres.md), run as the superuser on the
-- seeded data. The query runs without the ratings index (dropped inside a transaction
-- that is rolled back, so nothing changes) and then with it. That is the index the
-- query depends on: the average rating is computed once per restaurant found.
-- Usage: psql -v zone=<customer zone id> -v weekday=<0-6, Monday 0> -v minute=<0-1439>
--        -f postgres/sql/explain_catalogue.sql

-- Query 1 (F1): restaurants open now that deliver to a customer's zone, with the fee and
-- the average rating. The same query app/services/catalogue.py sends.
BEGIN;
DROP INDEX ix_ratings_restaurant_id_created_at;
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id, r.name, r.min_order_value, f.fee AS delivery_fee,
       (SELECT round(avg(rt.restaurant_score), 2)
          FROM ratings rt WHERE rt.restaurant_id = r.id) AS average_rating
  FROM restaurants r
  JOIN zone_fees f ON f.restaurant_zone_id = r.zone_id
 WHERE f.customer_zone_id = :zone
   AND r.status = 'open'
   AND EXISTS (SELECT 1 FROM opening_periods p
                WHERE p.restaurant_id = r.id AND p.weekday = :weekday
                  AND p.hours @> :minute)
 ORDER BY r.name, r.id;
ROLLBACK;

EXPLAIN (ANALYZE, BUFFERS)
SELECT r.id, r.name, r.min_order_value, f.fee AS delivery_fee,
       (SELECT round(avg(rt.restaurant_score), 2)
          FROM ratings rt WHERE rt.restaurant_id = r.id) AS average_rating
  FROM restaurants r
  JOIN zone_fees f ON f.restaurant_zone_id = r.zone_id
 WHERE f.customer_zone_id = :zone
   AND r.status = 'open'
   AND EXISTS (SELECT 1 FROM opening_periods p
                WHERE p.restaurant_id = r.id AND p.weekday = :weekday
                  AND p.hours @> :minute)
 ORDER BY r.name, r.id;
