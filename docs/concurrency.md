# Concurrency

The four rules that must hold under simultaneous requests, and how each one is protected:

| Rule | Flow | Protection | Backed by |
|---|---|---|---|
| 1. An order is assigned to exactly one courier | F4 | Lock the order, then the offer (`FOR UPDATE`), then insert the delivery | `UNIQUE (order_id)` on `deliveries` |
| 2. An item's daily stock never goes below zero | F2 | Conditional atomic `UPDATE ... WHERE remaining >= :q` | `CHECK (remaining >= 0)` |
| 3. A courier never has more active deliveries than the vehicle allows | F4 | Lock the courier row (`FOR UPDATE`), then count | — (write skew) |
| 4. A restaurant never has more orders in preparation than its kitchen capacity | F3 | Lock the restaurant row (`FOR UPDATE`), then count | — (write skew) |

Sections still to be written by their owners are marked *(to do: name)*.

## Isolation level

**`READ COMMITTED`**, PostgreSQL's default, with explicit row locks and conditional updates.

- **Why not `SERIALIZABLE`:** `SERIALIZABLE` would also catch the write skews, but it aborts one of two conflicting transactions with a serialization failure. Every endpoint would then need a retry loop, and under the 60-request tests many requests would fail and retry.
- **What we do instead:** each rule is a short critical section on one known row (the stock row, the order, the courier, the restaurant). Under `READ COMMITTED`, a locked row makes the next transaction wait. When it gets the row, it reads the committed value. A conditional `UPDATE` re-checks its `WHERE` on that new value. So requests queue up instead of failing, and the losers get a clean 409.
- **Transactions:** one per request, `with SessionLocal() as session, session.begin():`. Everything a flow writes commits together or not at all. Redis is only written after the commit.

## Rule 2: daily stock (F2, place order)

`take_stock` in `app/services/stock.py`, inside the order's transaction:

```sql
-- 1. Lazy reset: the first order of the day creates today's row from the configured value.
INSERT INTO daily_stock (item_id, stock_date, remaining)
SELECT id, :day, daily_stock FROM menu_items
 WHERE id = :item AND daily_stock IS NOT NULL
ON CONFLICT (item_id, stock_date) DO NOTHING;

-- 2. Check and write in one statement.
UPDATE daily_stock SET remaining = remaining - :qty
 WHERE item_id = :item AND stock_date = :day AND remaining >= :qty
RETURNING remaining;
```

**What happens with 60 simultaneous orders for the last 30 portions:**
1. All 60 run the `INSERT ... ON CONFLICT DO NOTHING`. One creates the row; the others wait on the primary key, then do nothing. Nothing runs at midnight.
2. All 60 reach the `UPDATE`. The first one locks the row, takes a portion and holds the lock until its order commits. The others wait for that lock.
3. When the first commits, PostgreSQL re-evaluates the next one's `WHERE` on the new row version (`READ COMMITTED`). If `remaining >= :qty` still holds, it takes a portion. Otherwise the `UPDATE` returns 0 rows.
4. 0 rows → `Conflict("sold out")` → 409, and the whole order transaction rolls back: no order, no lines, no payment.
5. `CHECK (remaining >= 0)` is the last line of defence. Even a buggy `UPDATE` cannot store a negative stock.

**Several items in one order:** an order with several limited items takes their stock in ascending `item_id` order. Two orders that share items lock the rows in the same order, so they wait for each other and never deadlock. Cancel and reject give portions back (`release_stock`) and lock the rows in the same ascending order.

**The stock day:** the stock is per Lisbon day (`Europe/Lisbon`). A cancel gives the portions back to the stock row of the **order's** day, so cancelling at 00:10 an order from 23:50 does not add portions to the new day.

### Naive version (`?mode=naive`)

`take_stock_naive` is reachable only with `?mode=naive` and `ENABLE_NAIVE_MODE=true`. It reads, checks in Python, and writes the absolute value, with no lock:

```sql
SELECT remaining FROM daily_stock WHERE item_id = :item AND stock_date = :day;   -- e.g. 30
-- Python: 30 >= 1 → new = 29
UPDATE daily_stock SET remaining = :new WHERE item_id = :item AND stock_date = :day;
```

**Why it breaks:** many requests read the same `remaining` before any of them writes. All of them pass the check and all of them write the same new value. This is a **lost update**: 60 orders exist, but the stock only went down by a few portions. No constraint fires, because the stock never goes negative; the data is simply wrong. That is why the rule needs the check and the write in one statement, not a `CHECK` alone.

### Scenario "last portions": outputs

`tests/concurrency/last_portions.py`:
- **Fixture:** deletes the previous run's data, then creates 1 restaurant open 00:00–24:00 every day, 1 item with daily stock 30, and 60 customers in a delivered zone.
- **Attack:** 60 `POST /customers/{id}/orders` of 1 portion each, `simulate=approved`, fired together with `httpx.AsyncClient` and `asyncio.gather`.
- **Check:** the rule holds if the stock is 0 and exactly 30 orders exist.

These outputs were taken with a temporary runner that calls the scenario's `fixture`, `attack` and `check`. *(to do: RodrigoDias123, take them again with the shared `tests/concurrency/run.py` when it exists, so all 12 outputs have the same format.)*

```
mode=naive succeeded=60 refused=0 failed=0 rule_holds=False orders=60 stock_left=25
mode=naive succeeded=60 refused=0 failed=0 rule_holds=False orders=60 stock_left=27
mode=naive succeeded=60 refused=0 failed=0 rule_holds=False orders=60 stock_left=28
mode=real succeeded=30 refused=30 failed=0 rule_holds=True orders=30 stock_left=0
mode=real succeeded=30 refused=30 failed=0 rule_holds=True orders=30 stock_left=0
mode=real succeeded=30 refused=30 failed=0 rule_holds=True orders=30 stock_left=0
```

- **Naive:** all 60 orders went through, but only 2–5 portions were taken, so 60 orders exist for 30 portions.
- **Real:** exactly 30 orders; the other 30 got 409 "sold out"; stock 0; no 5xx.

## Status changes (F3, F5)

Every status change starts with `lock_order` (`SELECT ... FOR UPDATE` on the order) and then checks the transition against the status it reads under the lock.

- **Two requests on the same order** run one after the other. Examples: a customer cancel and a restaurant `ready`, or two cancels.
- **The second one** sees the new status and gets 409.
- **Why it matters:** a cancel gives the stock back and refunds exactly once, and a cancel can never slip in after `picked_up`.

The status change, the history row, the stock release and the refund are in the same transaction.

## Rule 4: kitchen capacity (F3, restaurant accepts)

`ensure_kitchen_room` in `app/services/kitchen.py`, called by F3 accept after `lock_order` and before the order moves to `accepted`:

```sql
SELECT kitchen_capacity FROM restaurants WHERE id = :r FOR UPDATE;
SELECT count(*) FROM orders
 WHERE restaurant_id = :r AND status IN ('accepted', 'preparing', 'ready');
-- count >= capacity → 409 "kitchen is full"
```

- **Why the lock (write skew):** two accepts for **different** orders of the same restaurant each read "1 slot left", both pass, and each updates its own order row. Nothing conflicts, and the kitchen ends up over capacity.
- **What the lock does:** the `FOR UPDATE` on the restaurant row makes every accept for that restaurant wait for the previous one to commit, and the count then includes the order just accepted.
- **Lock order:** the order first, the restaurant second, in every flow, so there is no deadlock.

**Tested:** a script did what F3 accept does (lock the order, call the function, set `accepted`, one transaction). It fired 10 accepts at once for a restaurant with capacity 2 and 1 active order:

| Version | Run | Accepted | Refused (409) | Active orders at the end |
|---|---|---|---|---|
| with `FOR UPDATE` | 1, 2, 3 | 1 | 9 | 2 of 2 |
| same count, no lock | 1, 2, 3 | 10 | 0 | 11 of 2 |

The rule 4 scenario in `run.py` is an extension *(not done yet)*.

## Rule 1: one courier per order (F4)

`accept_offer` in `app/services/courier_offers.py`, one transaction per request:

```sql
-- 0. Learn the offer's order (no lock; order_id never changes). Not this courier's → 404.
SELECT order_id FROM delivery_offers WHERE id = :offer AND courier_id = :courier;
-- 1. Lock the order: every accept of this order queues here.
SELECT ... FROM orders WHERE id = :order FOR UPDATE;
-- 2. Lock the offer and read whether its 45 s are over, on PostgreSQL's clock.
SELECT ..., sent_at > now() - interval '45 seconds' AS fresh
  FROM delivery_offers WHERE id = :offer FOR UPDATE;
-- not 'pending' → 409; not fresh → 409 (and marked 'expired', see below)
-- 3. The order must still be waiting for a courier.
SELECT id FROM deliveries WHERE order_id = :order;            -- a row → 409
-- 4. Rule 3 (next section): lock the courier, count, refuse if full.
-- 5. Win.
INSERT INTO deliveries (order_id, courier_id) VALUES (:order, :courier);   -- UNIQUE (order_id)
UPDATE delivery_offers SET outcome = 'accepted' WHERE id = :offer;
UPDATE delivery_offers SET outcome = 'withdrawn'
 WHERE order_id = :order AND id <> :offer AND outcome = 'pending' RETURNING id;
```

**What happens with 50 simultaneous accepts of the same order:**
1. All 50 read their offer's order and try to lock it. One gets the lock; the other 49 wait.
2. The first finds its offer `pending` and fresh, inserts the delivery, marks its offer `accepted` and the other 49 `withdrawn`, and commits.
3. The next one gets the order lock, locks its own offer and reads it again under `READ COMMITTED`: it is now `withdrawn`. → 409 `offer is withdrawn`. The same for the other 48.
4. After the commit, the app deletes the order's `fd:offer:*` keys and writes the courier into the tracking hash.

**Lock order: order, then offer, then courier.** Cancel (`cancel_order`) and reoffer (`reoffer_order`) lock the order and then update its offers. If F4 locked the offer first and the order second, an accept and a cancel of the same order could each hold one lock and wait for the other: a deadlock. With the same order everywhere, they queue instead. The offer is read once without a lock only to learn which order to lock; that column never changes.

**Why `UNIQUE (order_id)` is the last guarantee:** the lock makes the accepts run one at a time, so in real mode the unique never fires. If a bug skipped the lock (the naive mode below does exactly that), PostgreSQL would still refuse the second delivery. A second guard, the partial unique index `uq_delivery_offers_one_accepted_per_order`, allows at most one `accepted` offer per order. In real mode a violation of one of these two constraints is turned into 409; any other `IntegrityError` stays a 500, because it would be a bug.

**Expired offers (lazy, no worker):** an offer is valid while `pending` and less than 45 s old. When an accept or decline finds it too old, the request answers 409. The 409 rolls the request's transaction back, so the router writes `expired` in a second short transaction (a conditional `UPDATE ... WHERE outcome = 'pending'`, so it changes nothing if the offer was withdrawn meanwhile). Reoffer also marks the order's old offers `expired`.

### Naive version (`?mode=naive`)

`accept_offer_naive`, reachable only with `?mode=naive` and `ENABLE_NAIVE_MODE=true`: it reads the offer, the order and the courier with no `FOR UPDATE`, checks in Python, and writes. It does not catch `IntegrityError`.

**Why it breaks:** all 50 requests read "no delivery yet" before any of them commits, and all try to insert one. The first insert holds the unique index entry; the others wait for it and, when it commits, fail with a unique violation, which surfaces as a 500. PostgreSQL still ends with one delivery, because the unique is the last line of defence: the race shows as 5xx, not as broken data. The delivery is inserted on its own before any offer row is touched, so the losers fail on the unique and not on a deadlock between offer rows.

### Scenario "same order": outputs

`tests/concurrency/same_order.py`:
- **Fixture:** deletes the previous run's data (as the owner, by fixed NIF and emails), then writes straight to PostgreSQL 1 `accepted` order, 50 active couriers (cars, no active delivery) and 50 `pending` offers sent just now. It does not depend on F2, F3 or F7.
- **Attack:** 50 `POST /couriers/{id}/offers/{offer_id}/accept`, fired together with `httpx.AsyncClient` and `asyncio.gather`. Keep-alive is off: after a 500, uvicorn closes the connection, and a reused one would fail in the client instead of counting the 500.
- **Check:** the rule holds if the order has exactly 1 delivery and 1 `accepted` offer.

Taken with the shared runner on the seeded data, 3 runs per mode:

**Real mode** (`uv run python tests/concurrency/run.py --scenario same-order --mode real`):
```
scenario:   same-order
mode:       real
requests:   50
succeeded:  1 (2xx)
refused:    49 (4xx)
failed:     0 (5xx)
rule holds: yes (deliveries=1 accepted_offers=1)
exit code: 0

scenario:   same-order
mode:       real
requests:   50
succeeded:  1 (2xx)
refused:    49 (4xx)
failed:     0 (5xx)
rule holds: yes (deliveries=1 accepted_offers=1)
exit code: 0

scenario:   same-order
mode:       real
requests:   50
succeeded:  1 (2xx)
refused:    49 (4xx)
failed:     0 (5xx)
rule holds: yes (deliveries=1 accepted_offers=1)
exit code: 0
```

**Naive mode** (`--mode naive`):
```
scenario:   same-order
mode:       naive
requests:   50
succeeded:  1 (2xx)
refused:    24 (4xx)
failed:     25 (5xx)
rule holds: yes (deliveries=1 accepted_offers=1)
exit code: 0

scenario:   same-order
mode:       naive
requests:   50
succeeded:  1 (2xx)
refused:    40 (4xx)
failed:     9 (5xx)
rule holds: yes (deliveries=1 accepted_offers=1)
exit code: 0

scenario:   same-order
mode:       naive
requests:   50
succeeded:  1 (2xx)
refused:    30 (4xx)
failed:     19 (5xx)
rule holds: yes (deliveries=1 accepted_offers=1)
exit code: 0
```

- **Real:** 1 accepted, 49 × 409, no 5xx, one delivery, every time.
- **Naive:** 9 to 25 requests failed with 500 (`uq_deliveries_order_id` violations in the API log). The rest got 409 because they read the order after the winner committed. How many fall on each side changes from run to run, because it depends on how the 50 requests interleave. PostgreSQL still has one delivery: here the unique, not the app, kept the rule. The runner exits 0 because the rule holds and, in naive mode, a 5xx is the race showing up rather than a failure of the test.

## Rule 3: vehicle limit (F4)

A courier never has more active deliveries than the vehicle allows: bicycle 1, scooter 2, car 3 (`VEHICLE_CAPACITY` in `app/models/couriers.py`). Active = not delivered yet and the order not cancelled.

Step 4 of `accept_offer`, after the order and the offer are locked:

```sql
SELECT ... FROM couriers WHERE id = :courier FOR UPDATE;      -- blocked → 409
SELECT count(*) FROM deliveries d JOIN orders o ON o.id = d.order_id
 WHERE d.courier_id = :courier AND d.delivered_at IS NULL AND o.status <> 'cancelled';
-- count >= capacity → 409 "no room left on the scooter"
```

- **Why the lock (write skew):** a scooter with 1 active delivery accepts two offers for **different** orders at once. Each request counts 1, sees room for 2, and inserts the delivery of its own order. The two writes touch different rows, so no constraint and no row lock stops them, and the scooter ends with 3.
- **What the lock does:** the `FOR UPDATE` on the courier row makes every accept by that courier wait for the previous one to commit. The count then runs after the lock is granted and, under `READ COMMITTED`, sees the delivery just inserted.
- **Why it is checked again in F4:** F3 already offers only to couriers with room, but that is a read without a lock, seconds earlier. The courier may have accepted another offer since.
- **Lock order:** order, offer, courier. Two accepts by one courier for different orders each hold their own order lock and then queue on the courier; nobody locks a courier and then an order, so there is no cycle.
- **Index:** the partial index `ix_deliveries_courier_active` `(courier_id) WHERE delivered_at IS NULL` serves the count (see [postgres.md](postgres.md), query 4).

### Scenario "vehicle limit" (extension): outputs

`tests/concurrency/vehicle_limit.py`:
- **Fixture:** a scooter (limit 2) with 1 active delivery, and 5 `pending` offers to it, each for a different `accepted` order, so rule 1 never refuses anything and only rule 3 is tested.
- **Attack:** the scooter accepts its 5 offers at the same time.
- **Check:** the rule holds if the scooter has at most 2 active deliveries.

Taken with the shared runner, 3 runs per mode:

**Real mode** (`uv run python tests/concurrency/run.py --scenario vehicle-limit --mode real`):
```
scenario:   vehicle-limit
mode:       real
requests:   5
succeeded:  1 (2xx)
refused:    4 (4xx)
failed:     0 (5xx)
rule holds: yes (active_deliveries=2 limit=2)
exit code: 0

scenario:   vehicle-limit
mode:       real
requests:   5
succeeded:  1 (2xx)
refused:    4 (4xx)
failed:     0 (5xx)
rule holds: yes (active_deliveries=2 limit=2)
exit code: 0

scenario:   vehicle-limit
mode:       real
requests:   5
succeeded:  1 (2xx)
refused:    4 (4xx)
failed:     0 (5xx)
rule holds: yes (active_deliveries=2 limit=2)
exit code: 0
```

**Naive mode** (`--mode naive`):
```
scenario:   vehicle-limit
mode:       naive
requests:   5
succeeded:  5 (2xx)
refused:    0 (4xx)
failed:     0 (5xx)
rule holds: NO (active_deliveries=6 limit=2)
exit code: 1

scenario:   vehicle-limit
mode:       naive
requests:   5
succeeded:  5 (2xx)
refused:    0 (4xx)
failed:     0 (5xx)
rule holds: NO (active_deliveries=6 limit=2)
exit code: 1

scenario:   vehicle-limit
mode:       naive
requests:   5
succeeded:  5 (2xx)
refused:    0 (4xx)
failed:     0 (5xx)
rule holds: NO (active_deliveries=6 limit=2)
exit code: 1
```

- **Real:** exactly one more delivery fits; the other 4 got 409; 2 active deliveries.
- **Naive:** all 5 accepted with no error at all, and the scooter has 6 active deliveries. Unlike rule 1, no constraint stands behind this rule, so the race leaves wrong data instead of a 5xx. That is why the lock is needed.
