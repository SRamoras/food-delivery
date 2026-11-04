# jcleberfernandes (C) — Catalogue, tracking and reports

> GitHub: **jcleberfernandes**

## Your part in one sentence

The customer opens the app and sees the restaurants that are open **right now** and deliver to their home (F1). After ordering, the app asks every 5 seconds "where is my food?" (F6), and thousands of customers do the same. **You make sure those questions do not knock PostgreSQL over**, because Redis answers them. At the end of the month the back office wants reports (F8), and you build that in MongoDB.

You are also the foundation of the data: cities, zones, customers, restaurants and menus are the tables everyone else depends on.

---

## What is yours

| Area | What you do |
|---|---|
| **PostgreSQL** | `cities`, `zones`, `zone_fees`, `customers`, `customer_addresses`, `restaurants`, cuisines, `opening_periods`, categories, `menu_items`, `ratings` |
| **App** | F1 (browse and menu), F6 (tracking), F8 (reports), the tracking and ranking functions A and B call |
| **Redis** | `fd:order:{id}:track`, `fd:rank:{city}:{minute}`, and their part of rebuild/verify |
| **MongoDB** | `export_reports.py`, `report_orders` and `report_offers` collections, pipelines 1 and 5 |
| **Concurrency** | The shared `tests/concurrency/run.py` (arguments, counting, output, exit code) |
| **Seed** | Cities, zones, fees, customers, addresses, restaurants, hours, menu, ratings. **The first PG seed to run.** |
| **Docs** | `docs/architecture.md`, `docs/mongodb.md`, the `EXPLAIN` for query 1 in `postgres.md`, MongoDB runbook |

---

## Understand these 5 ideas first

### 1. `EXCLUDE`: PostgreSQL stopping overlapping hours
A `UNIQUE` only forbids equal values. To forbid **12:00–15:00** and **14:00–16:00** existing on the same day, you use:
```sql
EXCLUDE USING gist (restaurant_id WITH =, weekday WITH =, hours WITH &&)
```
`&&` means "overlaps". `hours` can be an `int4range` in minutes (0 to 1440), which lets you represent **24:00** without trouble. It needs the `btree_gist` extension, which A creates in `setup.sh`.

### 2. Partial unique index: "at most one default address"
```sql
CREATE UNIQUE INDEX ... ON customer_addresses (customer_id) WHERE is_default;
```
Only rows with `is_default = true` go into the index, so each customer can have many addresses but only one default.

### 3. "Open now" is in Lisbon time
The server may run in UTC. "Now" is `datetime.now(ZoneInfo("Europe/Lisbon"))`: day of week + minute of the day. A restaurant is open if it has `status = 'open'` **and** a period on that day containing that minute.

### 4. Caching in Redis: the "cache-aside" pattern
```
GET /track → does fd:order:{id}:track exist in Redis?
   yes → answer from Redis only (never touch PostgreSQL)
   no  → read PG once, store it in Redis, answer
```
Whoever changes the status (A and B) calls your function to update the key **after** the commit. The trainer wants **proof**: Redis `MONITOR` showing the commands, next to the PostgreSQL log (`log_statement = 'all'`) showing **no** query for that request.

### 5. Reports: PG → export → Mongo → pipeline
The pipelines do not run on PostgreSQL. A script (`export_reports.py`) reads PG with the `fd_readonly` role and writes "ready to analyse" documents into Mongo, for example one document per order with its lines, the date of each status and the zone. That data is **derived**: if Mongo is lost, you run the export again. Then aggregation pipelines answer the brief's questions.

---

## Step by step

Your tables come first (right after A's infrastructure), because everyone's FKs point at them.

### Step 1 — Migration: geography and customers
- `cities`; `zones` with `UNIQUE (city_id, name)`; `zone_fees` (restaurant zone, customer zone, `fee numeric(10,2)` with `CHECK >= 0`, `UNIQUE` on the pair).
- `customers`: name, email `UNIQUE`, phone `UNIQUE`, `password_hash`, `registered_at`.
- `customer_addresses`: street, number, floor, postcode, zone (FK), notes, lat/lng, `is_default` + the partial unique index.
- ✅ **Done when:** a second default address for the same customer is refused.

### Step 2 — Migration: restaurants and menus
- `restaurants`: name, NIF `UNIQUE` + `CHECK (nif ~ '^[0-9]{9}$')`, address, zone, lat/lng, `min_order_value` (`CHECK >= 0`), `kitchen_capacity` (`CHECK > 0`), `status` (`open`/`closed`/`suspended`).
- `cuisines` + the association table `restaurant_cuisines` (N:N).
- `opening_periods` with the `EXCLUDE` from idea 1.
- `menu_categories`, `menu_items`: price (`CHECK >= 0`), `status` (`available`/`unavailable`), configured `daily_stock` (optional, `CHECK >= 0`; agree the name with B), `options jsonb`.
- Index for `EXPLAIN` query 1: restaurants open now that deliver to a zone.
- ✅ **Done when:** overlapping hours and 8-digit NIFs are refused.

### Step 3 — Options in `jsonb`
One possible shape:
```json
[
  {"type": "size", "required": true, "choices": [{"name": "small", "extra": 0}, {"name": "large", "extra": 2.00}]},
  {"type": "extras", "max": 3, "choices": [{"name": "cheese", "extra": 1.00}, {"name": "bacon", "extra": 1.50}]},
  {"type": "removals", "choices": [{"name": "no onion", "extra": 0}]},
  {"type": "allergens", "values": ["gluten", "lactose"]}
]
```
A Pydantic model validates this shape. B uses it to compute prices. In `mongodb.md`, explain why you chose `jsonb` and not Mongo: the price must be read **in the same transaction** as the order, and a new kind of option needs no schema change.

### Step 4 — F1: browse
- `GET /customers/{id}/addresses/{address_id}/restaurants`: restaurants that are `open`, with a period containing "now" (Lisbon), with a `zone_fees` row for the address's zone, with the fee and the average rating.
- `GET /restaurants/{id}/menu`: categories, items and the options of each.
- ✅ **Done when:** changing a restaurant's hours makes it disappear from the list.

### Step 5 — F6: tracking from Redis
- Function `update_tracking(order_id, status, courier_id)`, called by A and B after each commit: `HSET fd:order:{id}:track ...` + `EXPIRE` in the same `MULTI`.
- `GET /customers/{id}/orders/{order_id}/track`: read the hash; if there is a courier, `GEOPOS fd:couriers:geo {courier_id}` for the position. If the key does not exist, read PG once and store it.
- **Evidence:** turn on `log_statement = 'all'` in PG (A leaves a switch for it in `compose.yml`), run `MONITOR` in `redis-cli`, make the same request twice, and paste both logs into `redis.md` (give them to A, who writes that file).
- ✅ **Done when:** the second request shows up in `MONITOR` and nothing shows up in the PostgreSQL log.

### Step 6 — Last-hour ranking
- When B marks `delivered`, B calls your function: `ZINCRBY fd:rank:{city_id}:{yyyymmddHHMM} 1 {restaurant_id}` + `EXPIRE 3900`, in the same `MULTI`.
- To read: `ZUNION` of the last 60 buckets (one per minute), keep the top 20.
- ✅ **Done when:** delivering 3 orders from the same restaurant puts it at the top of its city.

### Step 7 — MongoDB: report collections and export
- In `mongodb/setup.py`, using A's `ensure_collection` helper: the `report_orders` and `report_offers` collections with their validators (B adds the pipeline 4 fields).
- `export_reports.py`: reads PG with `READONLY_DATABASE_URL` and writes:
  - `report_orders`: one document per finished order (city, zones, restaurant, cuisines, lines with options, date of each status, who cancelled and why, fee, tip);
  - `report_offers`: one document per offer (order, courier, zone, `sent_at`, outcome).
- Can run many times: it deletes and writes again.
- ✅ **Done when:** `seed.sh` runs the export and the collections are full.

### Step 8 — Pipelines 1 and 5, and F8
- Pipeline 1: *"Average delivery time (from placed to delivered) per zone and per hour of the day, for the last 30 days."* Needs `placed_at`, `delivered_at` and `customer_zone` in `report_orders`.
- Pipeline 5: *"For each restaurant, the average time between placed and accepted, and between accepted and ready."*
- One file per pipeline in `mongodb/pipelines/`.
- `GET /backoffice/reports/{name}`: runs the requested pipeline (your 1, B's 4, your 5) and returns the result.
- ✅ **Done when:** all 3 pipelines run through the endpoint and you have a sample output of each for `mongodb.md`.

### Step 9 — Shared concurrency script
`tests/concurrency/run.py`, with `--scenario same-order|last-portions` and `--mode naive|real`:
- calls each scenario's fixture and attack (written by A and B);
- counts 2xx, 4xx and 5xx;
- asks the scenario whether the rule holds in PG;
- prints the result and exits with 1 if the rule broke, or if there was any 5xx in real mode; otherwise 0.
- ✅ **Done when:** both scenarios use the same script and the output always has the same format.

### Step 10 — Seed (the first PG seed to run)
- 5 cities with 8–15 zones each, fees between pairs of nearby zones.
- 60k customers with 1–3 addresses (one default).
- 1,200 restaurants with non-overlapping hours (some with two periods, some 24h), 1–3 cuisines each.
- ~30k items with varied options; some with `daily_stock`.
- Ratings on ~40% of delivered orders (this step runs after B's and A's seeds).
- `random.seed(42)`, uneven (a few very popular restaurants), with `COPY`.

### Step 11 — Documentation (English)
- `docs/architecture.md`: source-of-truth table (each kind of data, owning engine, copies, which wins, what is lost), a Mermaid sequence diagram for F2, F4 and F6, what happens if the second write fails, how time-based state is handled (stock at midnight, 45 s offers, 30 s presence, 7-day TTL), security section (roles and users).
- `docs/mongodb.md`: each collection (why Mongo, truth or derived, example, validator, embed or reference), the options decision, the export, the 3 pipelines with output.
- `docs/postgres.md` (B owns it): your tables and constraints, and the `EXPLAIN (ANALYZE, BUFFERS)` without and with the index for query 1. The trick is `BEGIN; DROP INDEX ...; EXPLAIN ...; ROLLBACK;`.
- `docs/runbook.md`: the MongoDB section (`mongodump`/`mongorestore`; report collections are rebuilt with the export; positions are lost, but they are only 7 days of history).
- `README.md`: the ER diagram in Mermaid (everyone helps).

---

## Who you depend on

| You need… | From | For |
|---|---|---|
| Infrastructure (Compose, connections, Alembic, `ensure_collection`, `btree_gist`) | A | Everything |
| Orders and status changes | A and B | For tracking to have data and the export to have something to export |
| Courier positions in Redis | A | F6 |
| Scenario fixtures and attacks | A and B | Step 9 |

| They need you… | Who | For |
|---|---|---|
| **All** your tables | A and B | FKs and checks. That is why your migrations come first. |
| Tracking and ranking functions | A and B | They call them after every status change |
| `report_orders` export | B | Pipeline 4 |
| Restaurant coordinates | A | 3 km search |
| Tracking cache evidence | A | `redis.md` |

---

## Questions the trainer may ask you

- **"How do you guarantee two periods of the same restaurant do not overlap?"**
  With an `EXCLUDE USING gist`. PostgreSQL refuses any period of the same restaurant and day that overlaps (`&&`) another one.
- **"Why are the options in `jsonb` and not in tables, nor in Mongo?"**
  They change from restaurant to restaurant and new kinds appear without changing the schema. At the same time, the price must be read in the same transaction as the order, so they stay in PostgreSQL.
- **"Prove the tracking does not hit PostgreSQL."**
  I show Redis `MONITOR` with the `HGETALL` and the `GEOPOS`, next to the PostgreSQL log, empty at that moment.
- **"What happens if Redis disappears?"**
  The first tracking request goes to PG and refills the cache. `rebuild.py` recreates everything derived. The last-hour ranking is recomputed from the deliveries in PG.
- **"Why are reports in Mongo instead of running on PostgreSQL?"**
  So they do not load the database that serves orders. The documents are already grouped (order + lines + dates), which makes the aggregations simple. They are derived, and the export rebuilds them at any time.
- **"What is embedded and what is referenced in `report_orders`?"**
  Lines and status dates are embedded (always read together and they do not change after the order ends). The restaurant and the courier are referenced by id (they exist on their own and are shared by many orders).
- **"What is this index for?"**
  Answer with the query and the `EXPLAIN` before and after: from Seq Scan to Index Scan, how many buffers and how much time.

You must also be able to answer questions about A's and B's parts. Ask them to walk you through them.
