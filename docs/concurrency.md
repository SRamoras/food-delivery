# Concurrency

The four rules that must hold under simultaneous requests, and how each one is protected:

| Rule | Flow | Protection | Backed by |
|---|---|---|---|
| 1. An order is assigned to exactly one courier | F4 | Lock the offer and the order (`FOR UPDATE`), then insert the delivery | `UNIQUE (order_id)` on `deliveries` |
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

*(to do: SRamoras: the locks in F4 accept, why the `UNIQUE (order_id)` is the last guarantee, and the 6 outputs of the "same order" scenario.)*

## Rule 3: vehicle limit (F4)

*(to do: SRamoras.)*
