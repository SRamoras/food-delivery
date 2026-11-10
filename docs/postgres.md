# PostgreSQL

PostgreSQL is the source of truth: everything that must never be lost or contradict itself (orders, money, stock, assignments) lives here. MongoDB and Redis only hold copies or data that can be lost. The ER diagram is in [database-structure.md](database-structure.md).

Sections still to be written by their owners are marked *(to do: name)*.

## Tables

| Table | What it represents and why it exists |
|---|---|
| `cities` | A city the business works in. |
| `zones` | A delivery zone inside a city. Fees, delivered areas and reports are per zone. |
| `zone_fees` | The delivery fee from a restaurant's zone to a customer's zone. A missing pair means "not delivered there", so this table also answers "does this restaurant deliver to me?". |
| `customers` | A customer account. |
| `customer_addresses` | A customer's saved addresses (1–3), one of them the default. Separate from `customers` because a customer has several. |
| `cuisines`, `restaurant_cuisines` | The cuisine list and the many-to-many link to restaurants (a restaurant has 1–3). |
| `restaurants` | A restaurant: zone, position, minimum order, kitchen capacity, status. |
| `opening_periods` | One opening period of a restaurant on one weekday, as a range of minutes. A day can have several periods (lunch and dinner), so it is a table, not columns. |
| `menu_categories`, `menu_items` | A restaurant's menu. An item has a price, an optional daily stock and its options as `jsonb` (see [mongodb.md](mongodb.md) for why `jsonb`). |
| `daily_stock` | Portions left of an item on one Lisbon day. Created lazily by the first order of the day, so midnight needs no job. Rule 2. |
| `orders` | A customer order: restaurant, address snapshot, money, status, cancel data. |
| `order_lines` | One line of an order: item, quantity, unit price and options, all as they were when ordered. |
| `order_status_history` | Every status change of an order: old, new, who, when. Append-only. |
| `payments` | A simulated payment: the approved charge and, for cancelled or rejected orders paid online, the refund. |
| `couriers` | A courier: vehicle, plate, status. |
| `delivery_offers` | One offer of one order to one courier and its outcome. The record of what Redis holds for 45 s. |
| `deliveries` | The courier who won an order, with the accept, pickup and delivery times. Rule 1. |
| `ratings` | The customer's rating of a delivered order (restaurant and courier). |

## Where the rules are enforced

### Rules enforced by PostgreSQL itself

| Rule from the brief | How |
|---|---|
| An order has at most one courier | `uq_deliveries_order_id`: `UNIQUE (order_id)` on `deliveries`. Also `uq_delivery_offers_one_accepted_per_order`, a partial unique index, so that at most one offer per order is `accepted`. |
| An item's daily stock is never negative | `ck_daily_stock_remaining_nonneg`: `CHECK (remaining >= 0)`. The app takes stock with a conditional `UPDATE` (see [concurrency.md](concurrency.md)); the `CHECK` is the last line of defence. |
| Opening periods of a restaurant on one day never overlap | `ex_opening_periods_no_overlap`: `EXCLUDE USING gist (restaurant_id WITH =, weekday WITH =, hours WITH &&)`. It needs the `btree_gist` extension, which `setup.sh` creates. `hours` is an `int4range` of minutes, `[0,1440)`, so 24:00 is the upper bound 1440. `ck_opening_periods_hours_within_day` keeps it inside the day and not empty. |
| A customer has at most one default address | `uq_customer_addresses_one_default`: unique index on `(customer_id) WHERE is_default`. |
| Plate present for scooter and car, absent for bicycle | `ck_couriers_plate_by_vehicle` (multi-column `CHECK`). |
| Prices, fees, tips, totals and quantities in range; rating 1–5 | `CHECK`s: `menu_items.price`, `zone_fees.fee`, `orders.subtotal`/`delivery_fee`/`tip`/`total`, `payments.amount`, `order_lines.unit_price` ≥ 0; `order_lines.quantity` ≥ 1; `ratings.restaurant_score` and `courier_score` between 1 and 5. |
| Unique values | `UNIQUE`: `zones (city_id, name)`, `zone_fees (restaurant_zone_id, customer_zone_id)`, `customers.email` and `phone`, `restaurants.nif`, `couriers.email`, `phone` and `licence_plate`, `payments.provider_ref`, `ratings.order_id`. |
| NIF has 9 digits; statuses, vehicle types and payment methods restricted | `ck_restaurants_nif_format` (`nif ~ '^[0-9]{9}$'`); `CHECK ... IN (...)` on every status column, `couriers.vehicle_type` and `payments.method`. |
| The status history is never updated or deleted by the app role | Privileges: `fd_app` has only `INSERT` and `SELECT` on `order_status_history` (`REVOKE UPDATE, DELETE` in the orders migration). |

**Enforced in PostgreSQL beyond what the brief asks:**
- **Order totals:** `ck_orders_total_sum` checks `total = subtotal + delivery_fee + tip`.
- **Cancel data:** `ck_orders_cancelled_by_iff_cancelled` means a cancelled order says who cancelled it, and no other order does. `ck_orders_cancel_has_reason` requires a reason on every cancel, and the reason must come from the fixed list (`ck_orders_cancel_reason_valid`).
- **Payments:**
  - `ck_payments_provider_ref_by_method`: cash has no provider reference; card and MB WAY must have one.
  - `uq_payments_one_approved_per_order` and `uq_payments_one_refund_per_order`: an order is never charged or refunded twice.
- **History:** `ck_order_status_history_status_changes` rejects a row whose old and new status are the same.
- **Delivery times:** `ck_deliveries_picked_up_after_accepted` and `ck_deliveries_delivered_after_picked_up` keep the times in order.
- **Option snapshot:** `ck_order_lines_options_is_array` requires `order_lines.options` to be a JSON array.
- **Restaurant and menu ranges:** `kitchen_capacity > 0`, `min_order_value >= 0` and `menu_items.daily_stock >= 0`.

### Rules enforced in the app

#### Allowed status transitions

- **Where:** `app/services/order_status.py`. `ALLOWED` lists, for each status, the statuses it may move to. `ACTORS_FOR` lists who may make each move. `check_transition` raises 409 if either check fails. Every flow that changes an order goes through `change_status`, which writes the history row in the same transaction.
- **How it stays correct under concurrency:** the order row is locked first with `lock_order` (`SELECT ... FOR UPDATE`). Two changes on the same order run one after the other, and the second one is checked against the status the first one left.
- **Why in the app:** a transition depends on who is acting (the restaurant may reject, the customer may not), and the actor is known to the app, not to the row. A trigger would need the actor passed in some other way. With one shared function, F2, F3 and F5 all use the same table of rules.

#### Kitchen capacity (rule 4)

A restaurant never has more orders in `accepted`, `preparing` or `ready` than its `kitchen_capacity`.

- **Where:** `ensure_kitchen_room` in `app/services/kitchen.py`. F3 accept calls it in the same transaction, before it moves the order to `accepted`. Over capacity → 409 `kitchen is full`.
- **How:**
  1. Lock the restaurant row: `SELECT kitchen_capacity FROM restaurants WHERE id = :r FOR UPDATE`.
  2. Count the restaurant's active orders. The partial index `ix_orders_restaurant_active` holds only active orders, so the count reads a few rows, not the order history.
  3. Refuse if the count has reached the capacity.
- **Why a lock is needed:** this is a write skew. Two accepts for different orders of the same restaurant both count "one slot left", both pass, and each updates a different order row, so PostgreSQL sees no conflict between them. The `FOR UPDATE` on the restaurant row makes every accept for that restaurant wait for the previous one to commit. The next accept then counts the order just accepted. Under `READ COMMITTED`, the count runs after the lock is granted, so it sees the committed orders.
- **Lock order:** every flow locks the order first and the restaurant second, so two transactions never wait for each other in a circle.
- **Why in the app and not in PostgreSQL:** the rule counts rows in `orders` against a value in `restaurants`. A `CHECK` can only see one row, and a trigger would need the same lock and count, written in PL/pgSQL. The brief allows either. We chose the app because the lock, the count and the 409 sit in one short Python function, next to the order lock the flow already takes, and they are easier to read, test and explain.
- **Tested:**
  - capacity 2 with 2 orders in preparation → the third accept gets 409;
  - after one of them is cancelled, the third accept succeeds;
  - 10 simultaneous accepts with one slot left → 1 accepted and 9 refused, three times;
  - the same race without `FOR UPDATE` → all 10 accepted, so 11 active orders for capacity 2.

#### Maximum active deliveries per vehicle (rule 3)

Bicycle 1, scooter 2, car 3. *(to do: SRamoras, with F4.)* The group's design: F4 locks the courier row (`FOR UPDATE`) and then counts the courier's deliveries that are not delivered yet. The partial index `ix_deliveries_courier_active` serves that count. The lock is needed for the same write-skew reason as rule 4.

#### Minimum order value, opening hours, delivered zones

- **Where:** `place_order` in `app/services/orders.py` (F2), all inside the order's transaction and before any write.
  - The restaurant must be `open`.
  - An `opening_periods` row for today's weekday must contain the current minute, in Lisbon time.
  - A `zone_fees` row must exist for the restaurant's zone and the address's zone.
  - The subtotal, with options, must reach `min_order_value`.
  - Any failure → 409.
- **Why in the app:**
  - These checks depend on "now" in Lisbon time and read three other tables. A `CHECK` cannot do either.
  - A trigger could, but the 409 must say which rule failed, and the app already has these rows in hand to compute the fee and the prices.
  - None of these rules is a race that loses data. A restaurant closing a second after an order is placed is an accepted business case, not a broken invariant. So the reads need no lock.

## Denormalisations

All deliberate:

| Column(s) | Copied from | Why |
|---|---|---|
| `orders.delivery_*` (street, number, floor, postcode, zone, lat/lng, notes) | `customer_addresses` | The address is a historical fact: where this order was delivered. If the customer edits or deletes the address later, old orders must not change. `source_address_id` keeps the link and becomes `NULL` (`ON DELETE SET NULL`) if the address is deleted. |
| `order_lines.item_name`, `unit_price`, `options` | `menu_items` (name, price, options) | Menus and prices change; an order keeps what the customer saw and paid. The options snapshot also keeps the extra paid for each choice. |
| `orders.total` | `subtotal + delivery_fee + tip` | Stored because it is the amount charged and refunded. `ck_orders_total_sum` keeps it equal to its parts. |
| `orders.cancelled_by`, `orders.cancel_reason` | the last history row | Pipeline 4 (cancellations) and the report export read them without a join to the history. `ck_orders_cancelled_by_iff_cancelled` keeps them in step with the status. |

## Indexes

Indexes created by a primary key or a `UNIQUE` constraint are listed with the rules above. The others:

| Index | Serves |
|---|---|
| `ix_orders_customer_id_created_at` `(customer_id, created_at DESC)` | Frequent query 2: a customer's orders, newest first. It also covers the `customer_id` FK. |
| `ix_orders_restaurant_active` `(restaurant_id, created_at) WHERE status IN ('accepted','preparing','ready')` | Frequent query 3 (the kitchen screen) and the rule 4 count. Partial: it holds only the few active orders, not the whole history. It also covers the `restaurant_id` FK for active rows, and the restaurant FK check falls back to a scan only when a restaurant is deleted, which `RESTRICT` refuses anyway if it has orders. |
| `ix_order_lines_order_id` | An order's lines (order detail, refund, stock release). Covers the FK. |
| `ix_order_status_history_order_id_changed_at` | Frequent query 5: an order's history in time order. Covers the FK. |
| `ix_payments_order_id` | An order's payments (refund check). Covers the FK. |
| `ix_customer_addresses_customer_id` | A customer's addresses (F1, F2). Covers the FK. |
| `ix_restaurants_zone_id_open` `(zone_id) WHERE status = 'open'` | Frequent query 1 (F1): open restaurants of a zone. *(to do: jcleberfernandes, EXPLAIN query 1.)* |
| `ix_zone_fees_customer_zone_id` | F1: the restaurant zones that deliver to a customer's zone. The unique index starts with `restaurant_zone_id`, so it cannot serve this. |
| `ix_menu_categories_restaurant_id`, `ix_menu_items_category_id` | A restaurant's menu (F1, F2). Cover the FKs. |
| `ix_deliveries_courier_active` `(courier_id) WHERE delivered_at IS NULL` | Frequent query 4 and the rule 3 count: a courier's active deliveries. *(to do: SRamoras, EXPLAIN query 4.)* |
| `ix_ratings_restaurant_id_created_at` | Frequent query 6: a restaurant's average rating in the last 90 days. |
| `ex_opening_periods_no_overlap` (GiST) | Backs the `EXCLUDE` constraint. It also finds a restaurant's periods for a weekday (F1, F2). |

### EXPLAIN evidence

Run on the seeded data: 418,631 orders. Queries 2 and 3 are in `postgres/sql/explain_orders.sql`. Each query runs without its index (dropped inside a transaction that is rolled back) and then with it:

```bash
docker compose exec -T postgres psql -U postgres -d food_delivery \
  -v customer=5541 -v restaurant=137 -f - < postgres/sql/explain_orders.sql
```

#### Query 1: open restaurants delivering to a zone

*(to do: jcleberfernandes.)*

#### Query 2: a customer's orders, newest first, 20 per page

```sql
SELECT id, restaurant_id, status, total, created_at
  FROM orders WHERE customer_id = 5541
 ORDER BY created_at DESC LIMIT 20;
```

Customer 5541 is the busiest one, with 251 orders.

**Without `ix_orders_customer_id_created_at`:**
```
 Limit  (cost=10555.32..10557.65 rows=20 width=31) (actual time=7.994..8.967 rows=20 loops=1)
   Buffers: shared hit=871 read=6577 written=8
   ->  Gather Merge  (cost=10555.32..10580.99 rows=220 width=31) (actual time=7.993..8.965 rows=20 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         Buffers: shared hit=871 read=6577 written=8
         ->  Sort  (cost=9555.30..9555.57 rows=110 width=31) (actual time=6.710..6.711 rows=15 loops=3)
               Sort Key: created_at DESC
               Sort Method: top-N heapsort  Memory: 27kB
               ->  Parallel Seq Scan on orders  (cost=0.00..9552.37 rows=110 width=31) (actual time=0.097..6.664 rows=84 loops=3)
                     Filter: (customer_id = 5541)
                     Rows Removed by Filter: 139460
 Planning Time: 0.239 ms
 Execution Time: 8.995 ms
```

**With it:**
```
 Limit  (cost=0.42..80.17 rows=20 width=31) (actual time=0.011..0.032 rows=20 loops=1)
   Buffers: shared hit=22
   ->  Index Scan using ix_orders_customer_id_created_at on orders  (cost=0.42..1057.05 rows=265 width=31) (actual time=0.010..0.031 rows=20 loops=1)
         Index Cond: (customer_id = 5541)
         Buffers: shared hit=22
 Planning Time: 0.087 ms
 Execution Time: 0.040 ms
```

**Reading:**
- **Without the index:** PostgreSQL reads the whole table (7,448 buffers, 418k rows filtered down to 251), then sorts to find the newest 20.
- **With the index:** it walks the index already in `created_at DESC` order for that customer and stops after 20 rows. It reads 22 buffers and needs no sort node.
- **Why the column order matters:** `(customer_id, created_at DESC)` serves both the filter and the `ORDER BY`. That is why it is one composite index and not an index on `customer_id` alone.
- **Result:** about 220 times faster, and it stays flat as the table grows.

#### Query 3: a restaurant's orders in accepted, preparing or ready (kitchen screen)

```sql
SELECT id, customer_id, status, created_at
  FROM orders
 WHERE restaurant_id = 137 AND status IN ('accepted', 'preparing', 'ready')
 ORDER BY created_at;
```

Restaurant 137 has the most active orders right now: 8.

**Without `ix_orders_restaurant_active`:**
```
 Sort  (cost=11206.92..11206.93 rows=4 width=25) (actual time=11.767..12.699 rows=8 loops=1)
   Sort Key: created_at
   Sort Method: quicksort  Memory: 25kB
   Buffers: shared hit=855 read=6523 written=38
   ->  Gather  (cost=1000.00..11206.88 rows=4 width=25) (actual time=11.685..12.694 rows=8 loops=1)
         Workers Planned: 2
         Workers Launched: 2
         ->  Parallel Seq Scan on orders  (cost=0.00..10206.48 rows=2 width=25) (actual time=10.823..10.849 rows=3 loops=3)
               Filter: ((restaurant_id = 137) AND ((status)::text = ANY ('{accepted,preparing,ready}'::text[])))
               Rows Removed by Filter: 139541
 Planning Time: 0.073 ms
 Execution Time: 12.708 ms
```

**With it:**
```
 Sort  (cost=20.00..20.01 rows=4 width=25) (actual time=0.011..0.012 rows=8 loops=1)
   Sort Key: created_at
   Sort Method: quicksort  Memory: 25kB
   Buffers: shared hit=6
   ->  Bitmap Heap Scan on orders  (cost=4.18..19.96 rows=4 width=25) (actual time=0.006..0.009 rows=8 loops=1)
         Recheck Cond: ((restaurant_id = 137) AND ((status)::text = ANY ('{accepted,preparing,ready}'::text[])))
         Heap Blocks: exact=5
         ->  Bitmap Index Scan on ix_orders_restaurant_active  (cost=0.00..4.17 rows=4 width=0) (actual time=0.003..0.003 rows=8 loops=1)
               Index Cond: (restaurant_id = 137)
               Buffers: shared hit=1
 Planning Time: 0.102 ms
 Execution Time: 0.017 ms
```

**Reading:**
- **Why the index is partial:** active orders are a few hundred out of 418k. The index holds only rows whose status is `accepted`, `preparing` or `ready`. So the `Index Cond` only needs `restaurant_id`, and the status filter is already answered by the index predicate.
- **Cost:** it reads 1 index page and 5 table pages, instead of 7,378 buffers.
- **Size:** it stays tiny because orders leave it when they are picked up, delivered or cancelled. The same index serves the rule 4 count in `ensure_kitchen_room`.

#### Query 4: a courier's active deliveries

*(to do: SRamoras.)*

## Foreign keys: indexed and not indexed

PostgreSQL does not index a foreign key by itself. An index on the child column helps joins and lookups from the parent. It also speeds up the check made when a parent row is deleted (`RESTRICT`, `CASCADE`, `SET NULL`).

**Indexed:** the index leads with the FK column, either its own index or a composite or unique one.
- `zones.city_id`, through the unique `(city_id, name)`;
- `customer_addresses.customer_id`;
- `zone_fees.restaurant_zone_id` (unique) and `customer_zone_id`;
- `restaurants.zone_id`, partial, for open restaurants;
- `menu_categories.restaurant_id` and `menu_items.category_id`;
- `opening_periods.restaurant_id`, through the GiST index;
- `restaurant_cuisines.restaurant_id`, through the primary key;
- `daily_stock.item_id`, through the primary key;
- `orders.customer_id` and `orders.restaurant_id`;
- `order_lines.order_id`, `order_status_history.order_id` and `payments.order_id`;
- `deliveries.order_id` (unique) and `deliveries.courier_id` (partial);
- `delivery_offers.order_id`, through the unique `(order_id, courier_id)`;
- `ratings.order_id` (unique) and `ratings.restaurant_id`.

**Not indexed, on purpose:**

| FK | Why no index |
|---|---|
| `customer_addresses.zone_id`, `orders.delivery_zone_id` | No query looks up addresses or orders by zone in PostgreSQL; the zone reports run in MongoDB. Zones are never deleted in normal operation, so the `RESTRICT` check that would scan these tables does not run. |
| `restaurant_cuisines.cuisine_id` | Cuisines are a short fixed list that is never deleted. Filtering by cuisine is not a PostgreSQL query here. |
| `order_lines.item_id` | No query reads lines by item; item sales are a MongoDB report. Items with orders are never deleted (`RESTRICT`); they are marked `unavailable` instead. An index on 1.1M lines would only slow down every order insert. |
| `orders.source_address_id` | Only kept as a link; orders are read through their own snapshot. Deleting an address (`SET NULL`) scans `orders`, which is acceptable for a rare action. If it became frequent, this is the index to add. |
| `delivery_offers.courier_id` | *(to do: SRamoras, confirm: F4 reads an offer by its id, not by courier.)* |

## Roles

*(to do: SRamoras.)*
