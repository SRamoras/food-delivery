# PostgreSQL

## Where the rules are enforced

### Rules enforced in the app

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
