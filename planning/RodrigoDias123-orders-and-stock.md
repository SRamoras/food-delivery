# RodrigoDias123 (B) — Orders and stock

> GitHub: **RodrigoDias123**

## Your part in one sentence

It is 20:00 on a Friday. A restaurant cooked 30 portions of the dish of the day, and 60 people press "Order" in the same second. **You make sure exactly 30 succeed**, and the other 30 get a polite "sold out" instead of an error.

You own the life of an order: it is born in your code (F2), goes through the kitchen (preparing, ready), the courier picks it up and delivers it, or it dies cancelled or rejected. **All of F5 is yours.** Infrastructure, couriers and offers are A's; the catalogue, tracking and reports are C's.

---

## What is yours

| Area | What you do |
|---|---|
| **PostgreSQL** | Tables `daily_stock`, `orders`, `order_lines`, `payments`, `order_status_history` and their constraints |
| **App** | F2 (place order) real and naive; all of F5: preparing, ready, picked_up, delivered, cancel; the function that gives stock back |
| **Redis** | The stock key `fd:stock:{item_id}:{date}` and its part in `rebuild.py` and `verify.py` |
| **MongoDB** | Pipeline 4: cancellations by reason and by who cancelled (+ its fields in the `report_orders` validator) |
| **Concurrency** | The **last portions** scenario (60 customers, 30 portions); the kitchen capacity check (mandatory); the rule 4 test scenario if there is time |
| **Seed** | Orders, lines, payments, history, stock |
| **Docs** | Owner of `docs/postgres.md` and `docs/concurrency.md` (you collect A's and C's sections), PostgreSQL runbook |

---

## Understand these 5 ideas first

### 1. A transaction is "all or nothing"
Placing an order writes to several tables: the order, the lines, the payment, the history and the stock. If anything fails halfway (for example the payment is declined), **nothing** may stay written. So all of it happens inside one `with session.begin():`. If an error is raised inside, PostgreSQL undoes everything by itself.

### 2. Why "read, check, write" breaks under concurrency
```
Request 1: reads stock = 1
Request 2: reads stock = 1      ← has not seen request 1's write yet
Request 1: 1 ≥ 1 → writes 0 ✔
Request 2: 1 ≥ 1 → writes 0 ✔   ← two orders, one portion
```
This is exactly the **naive version** you write on purpose, to show the problem.

### 3. The fix: check and write in the same SQL statement
```sql
UPDATE daily_stock
SET remaining = remaining - :qty
WHERE item_id = :item_id AND stock_date = :today AND remaining >= :qty
RETURNING remaining;
```
PostgreSQL locks the row while it runs the `UPDATE`. The second request **waits** for the first to finish, then sees the new value. If the statement returns 0 rows, there was no stock: return 409. The `CHECK (remaining >= 0)` stays as an extra safety belt.

### 4. The order keeps a "photo"
If the customer moves house tomorrow, or the restaurant raises its prices, old orders must not change. So you copy the address into `orders` and the unit price (item + options) into `order_lines`. This is not lazy denormalisation: it is a business rule. Write that in `postgres.md`.

### 5. The status machine
```
placed → accepted → preparing → ready → picked_up → delivered
placed → rejected                     (restaurant only)
placed/accepted/preparing/ready → cancelled   (customer, restaurant or back office, with a reason)
```
Any other transition is a 409. Every change inserts a row in the history **in the same transaction**, and the history is never changed (the app role does not even have permission). A does `placed → accepted` and `placed → rejected` inside F3; everything else is yours. Write the transition check as **one shared function** so A uses it too.

---

## Step by step

### Step 1 — Daily stock migration
- Table `daily_stock`: `item_id` (FK to `menu_items`), `stock_date` (`date`), `remaining` (`integer`). PK `(item_id, stock_date)`.
- `CHECK (remaining >= 0)`.
- The configured value (the 30 portions) lives in a `daily_stock` column on `menu_items`, which belongs to C. Agree on the name with her.
- ✅ **Done when:** `alembic upgrade head` creates the table and an `UPDATE` to -1 is refused by PostgreSQL.

### Step 2 — Orders migration
- `orders`: customer, restaurant, address copy (street, number, postcode, zone, lat/lng, notes), `subtotal`, `delivery_fee`, `tip`, `total` (all `numeric(10,2)` with `CHECK >= 0`), `status` with a `CHECK` on the allowed values, `cancel_reason`, `created_at timestamptz`.
- `order_lines`: order, item, `quantity` with `CHECK >= 1`, `unit_price` with `CHECK >= 0`, `options jsonb`.
- `payments`: order, `amount`, `method` (`card`/`mbway`/`cash`), `status` (`approved`/`declined`/`refunded`), `paid_at`, `provider_ref` with `UNIQUE`, and a `CHECK`: cash without a reference, card and MB WAY with one.
- `order_status_history`: order, `old_status`, `new_status`, `actor_type`, `actor_id`, `changed_at`.
- In the migration, with `op.execute`: `REVOKE UPDATE, DELETE ON order_status_history FROM fd_app;`
- Indexes: "a customer's orders, newest first" and "a restaurant's orders in accepted/preparing/ready". These are `EXPLAIN` queries 2 and 3.
- ✅ **Done when:** the migration applies to an empty database and, connected as `fd_app`, an `UPDATE order_status_history` fails with a permission error.

### Step 3 — F2: place order (real version)
`POST /customers/{customer_id}/orders`, body: address, lines (item, quantity, options), tip, payment method and `simulate`.

Inside **one** transaction, in this order:
1. `simulate = declined` → 409, nothing written.
2. Is the address this customer's? → otherwise 404.
3. Restaurant `open`? Within its hours **now, in Lisbon time**? Delivers to the address's zone (a row exists in `zone_fees`)? → otherwise 409.
4. Every item `available` and from the same restaurant? → otherwise 409.
5. Compute prices: item + chosen options (read from the `jsonb`). Subtotal ≥ the restaurant's minimum? → otherwise 409.
6. For each item with stock: create today's row if missing (`INSERT ... ON CONFLICT DO NOTHING` with the configured value), then the `UPDATE ... WHERE remaining >= :qty`. 0 rows → 409 "sold out", and the transaction undoes everything.
7. Insert the order, the lines, the `approved` payment and the history (`None → placed`).
8. After the commit: update the stock in Redis and the tracking (C's function).

- ✅ **Done when:** you can place an order from `/docs`, and one with `simulate=declined` returns 409 and leaves nothing in PostgreSQL.

### Step 4 — F2 naive version
With `?mode=naive` (and only if `ENABLE_NAIVE_MODE=true`): **read** the stock with a `SELECT`, **check** in Python, **write** with another `UPDATE`. No lock, on purpose.
- ✅ **Done when:** the last portions test in naive mode gives more than 30 successes, or 500 errors.

### Step 5 — Stock in Redis
- Key `fd:stock:{item_id}:{yyyy-mm-dd}` with the remaining value, written **after** the PG commit with `SET ... EXAT <next Lisbon midnight + margin>`. The expiry goes in the same command.
- PostgreSQL stays the truth. Redis is only a copy for fast reads (class: derived).
- In `redis/rebuild.py`: rebuild these keys from PG. In `redis/verify.py`: compare them with PG.
- Give A the details of this key for `redis.md`.
- ✅ **Done when:** `FLUSHALL` → rebuild → verify exits with 0.

### Step 6 — F5: restaurant side and cancel
- `POST /restaurants/{id}/orders/{order_id}/preparing` and `/ready`.
- `POST /customers/{id}/orders/{order_id}/cancel`, `POST /restaurants/{id}/orders/{order_id}/cancel` and `POST /backoffice/orders/{order_id}/cancel`, with a reason. The history records who cancelled (customer, restaurant or back office); pipeline 4 groups by it.
- Each one: `SELECT ... FOR UPDATE` on the order, check the transition is allowed (otherwise 409), update, insert into the history, update tracking.
- Cancel and reject **give the stock back**. If paid by card or MB WAY, insert a `refunded` payment with the same amount. Write this as a function A calls when the restaurant rejects.
- If there was already a courier, their delivery stops being active. Agree with A how that is marked in `deliveries`.
- ✅ **Done when:** a cancellation gives the portions back and creates the refund, and trying `ready → preparing` returns 409.

### Step 7 — F5: courier side
- `POST /couriers/{id}/deliveries/{order_id}/picked-up`: the delivery must belong to this courier and the order must be `ready` → `picked_up`, history, `picked_up_at` in `deliveries` (A's table).
- `POST /couriers/{id}/deliveries/{order_id}/delivered`: `picked_up → delivered`, `delivered_at`, `distance_km`, history. Then update tracking and the ranking (C's functions).
- ✅ **Done when:** one order goes all the way from `placed` to `delivered`.

### Step 8 — "Last portions" concurrency scenario
In `tests/concurrency/` (the shared script is C's; you write your scenario):
- **Fixture:** delete what is left from the previous run and create 1 restaurant open 00:00–24:00 every day, 1 item with stock 30, and 60 customers with an address in a delivered zone. It may write straight to the DB.
- **Attack:** 60 `POST /customers/{id}/orders` at the same time, with `simulate=approved`.
- **Check in PG:** stock = 0 and exactly 30 orders.
- ✅ **Done when:** real mode gives 30/30/0 three times in a row and naive mode breaks.

### Step 9 — Seed
- Orders over the last 12 months (**≥400k**), lines (**≥1M**), payments, one history row per status reached. ~5% cancelled (with reason and refund where it applies), ~2% rejected.
- Uneven: some customers and restaurants with many more orders.
- Use psycopg `cursor.copy(...)`. Generate in memory and write in batches.
- Runs **after** C's seed (you need customers, restaurants and items) and **before** A's courier seed (he needs the orders to create offers and deliveries).
- ✅ **Done when:** the whole group's seed takes under 5 minutes.

### Step 10 — Pipeline 4 in MongoDB
- *"Cancellations by reason and by who cancelled, per restaurant, in the last 90 days."*
- Runs on `report_orders`, which C exports. Agree with her that documents carry `status`, `cancel_reason`, `cancelled_by`, `restaurant_id` and the dates; add those fields to the validator.
- File in `mongodb/pipelines/`.
- ✅ **Done when:** the pipeline runs and you have a sample output for `mongodb.md`.

### Step 11 — Kitchen capacity (rule 4, mandatory)
The brief says a restaurant **cannot** accept an order when it already has as many orders in `accepted`/`preparing`/`ready` as its kitchen capacity. Applying it is mandatory; only its test scenario is an extension.
- Write a function A calls inside F3 accept: `SELECT ... FROM restaurants WHERE id = :r FOR UPDATE`, count the restaurant's orders in `accepted`/`preparing`/`ready`, raise 409 if it reached `kitchen_capacity`.
- The lock on the restaurant row makes two accepts for the same restaurant queue up, so they cannot both see "one slot left".
- Say in `postgres.md` that this rule is enforced in the app, and why.
- ✅ **Done when:** a restaurant with capacity 2 and 2 orders in preparation gets 409 on a third accept.
- *(extension)* Add a rule 4 scenario to `run.py`, with naive and real modes.

### Step 12 — Documentation (English)
- `docs/postgres.md` (**you own it**): every table and what it represents, every constraint and index with the rule or query it serves, both lists from "Where the rules are enforced" with how and where each rule is enforced, denormalisations (the address and price snapshots), the 3 `EXPLAIN` (you do 2 and 3; C does 1; A does 4), indexed and non-indexed FKs. A writes the roles section.
- `docs/concurrency.md` (**you own it**): isolation level, your conditional `UPDATE`, why the naive version breaks, your 6 outputs; A adds the F4 section and his 6 outputs.
- `docs/runbook.md`: the PostgreSQL section, with the 5 points the README asks for:
  1. what is backed up, how often, with which tool and where (for example `pg_dump` daily plus WAL archiving, or `pg_basebackup`);
  2. the exact backup and restore commands, in order (restoring as the owner role, then re-running grants if needed);
  3. how you verify it (row counts per table, a known query, the app's `/health`);
  4. RTO and RPO, justified by the business: losing payments means customers who paid with no record of it, so the RPO must be small, which a daily `pg_dump` alone cannot meet;
  5. what is lost for good, and that PostgreSQL is the source of truth, so Mongo reports and Redis keys are rebuilt from it afterwards.
- `docs/ai-usage.md`: your entries.

---

## Who you depend on

| You need… | From | For |
|---|---|---|
| Infrastructure (Compose, connections, Alembic) | A | Everything |
| Customer, address, restaurant, hours, item and `zone_fees` tables | C | Step 2 (FKs) and step 3 (checks) |
| `deliveries` table | A | Step 7 |
| Tracking and ranking functions | C | Steps 3, 6 and 7 |
| `report_orders` export | C | Step 10 |

| They need you… | Who | For |
|---|---|---|
| Working F2 | A | For the restaurant to accept and create offers |
| `orders` table | A | FKs of `delivery_offers` and `deliveries` |
| Function that gives stock back | A | When the restaurant rejects |
| Kitchen capacity check | A | Called inside F3 accept |
| Shared transition check | A | `placed → accepted/rejected` in F3 |
| Orders seed | A and C | Offers, deliveries and ratings seed |

---

## Questions the trainer may ask you

- **"What happens if two customers order the last portion at the same time?"**
  The `UPDATE ... WHERE remaining >= 1` locks the row. The second waits, sees `remaining = 0`, the condition fails, 0 rows come back and we answer 409.
- **"Why not check the stock in Python?"**
  Between reading and writing another request can change the value. That is the naive version, and the test shows it breaks.
- **"Why is the stock in PostgreSQL and not only in Redis?"**
  It must never be lost or contradict itself. Redis is only a copy for fast reads; if it disappears, the rebuild recreates it from PG.
- **"How does the stock go back to 30 at midnight?"**
  There is no job. The row is per day (`stock_date`); when the first request of the new day comes in (Lisbon time), we create the row with the configured value.
- **"Copying the address into the order breaks 3NF, no?"**
  The order's address is a historical fact: where it was delivered that day. It is not the same information as the customer's current address.
- **"How do you guarantee the history is never changed?"**
  `REVOKE UPDATE, DELETE` from `fd_app`. Even a bug in the app cannot change it.
- **"Where are the status transitions enforced, and why there?"**
  In the app, in one shared function, with `FOR UPDATE` on the order so two changes cannot cross. (Or a trigger, if you choose that; say it in `postgres.md`.)
- **"What if Redis fails after the PostgreSQL commit?"**
  The order exists anyway (PG is the truth). The Redis stock is stale until the next write or the rebuild, and `verify.py` detects the difference.

You must also be able to answer questions about A's and C's parts. Ask them to walk you through them.