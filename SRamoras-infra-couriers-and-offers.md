# SRamoras (A) — Infrastructure + couriers and offers

> GitHub: **SRamoras**

## Your part in one sentence

You have the two hardest jobs in the project.

**First, you build the house.** Before anyone can write a single endpoint, the project has to start: three databases in Docker, an API container, the users and passwords, the migration tool, the scripts that set everything up from zero. That is you. If the trainer cannot run `setup.sh` and `seed.sh` from a clean clone, every part that needs a running system is graded on documents only, with at most half of its points.

**Then, you guard the "Accept" button.** A restaurant accepts an order. The app pings 5 couriers nearby and, in the same second, 3 of them press "Accept". You make sure only one gets the order. If two thought they won, both would ride to the restaurant and one would go home unpaid.

---

## What is yours

| Area | What you do |
|---|---|
| **Infrastructure** | `compose.yml`, `Dockerfile`, `pyproject.toml`, `.env.example`, `.gitignore`, `scripts/setup.sh`, `scripts/seed.sh`, `.devcontainer/` |
| **App** | `app/main.py`, `app/config.py`, `app/db/*`, `app/errors.py`; F7 (online, position, offline), F3 (accept, reject, reoffer), F4 (courier accepts) real and naive |
| **PostgreSQL** | `alembic.ini`, `migrations/env.py`, the grants migration; tables `couriers`, `delivery_offers`, `deliveries` |
| **MongoDB** | `mongodb/setup.py` base (app user, `ensure_collection` helper the others reuse); the `courier_positions` collection with its 7-day TTL |
| **Redis** | `redis/rebuild.py` and `redis/verify.py` skeletons; `fd:couriers:geo`, `fd:courier:{id}:online`, `fd:offer:{id}`; the position Lua script |
| **Concurrency** | The **same order** scenario (50 couriers, 1 order) + rule 3 (vehicle limit) if there is time |
| **Seed** | `seed.sh` orchestration + couriers, offers, deliveries, ≥50k positions in Mongo |
| **Docs** | README "how to run" section, `docs/redis.md` (all keys), your half of `concurrency.md`, Redis runbook |

Careful: files in the root and in `scripts/` **count for no area**. That is why your slice also has real work in `app/`, `postgres/`, `mongodb/` and `redis/`.

---

# Part 1 — Infrastructure

Do this first, as fast as you can: B and C are waiting on it. Push small working pieces early (for example `compose.yml` + `.env.example` on day one) instead of everything at the end.

## Understand these 4 ideas first

### 1. Three database roles, three jobs
| Role | Used by | Can do |
|---|---|---|
| `postgres` (superuser) | only `setup.sh`, step 1 | create the database, the roles and the extensions |
| `fd_owner` | Alembic (migrations) | own and create tables |
| `fd_app` | the API | read and write data; **no** `CREATE`, no `DROP`, no `UPDATE`/`DELETE` on the status history |
| `fd_readonly` | report export, DbGate | only `SELECT` |

This is "least privilege": if the app has a bug or an injection, it still cannot drop tables. The trainer checks it.

### 2. `ALTER DEFAULT PRIVILEGES`
`GRANT SELECT ON ALL TABLES` only applies to tables that exist **now**. B and C will create tables later. `ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner ... GRANT ...` says "every table `fd_owner` creates from now on automatically gets these grants". Put it in the first migration and nobody has to remember grants again.

### 3. Idempotent scripts
`setup.sh` and `mongodb/setup.py` must be able to run twice without failing. Use "create if it does not exist": `CREATE ROLE` inside a `DO $$ ... IF NOT EXISTS ...`, `createCollection` only when the collection is missing (otherwise `collMod`), `create_index` (already safe to repeat).

### 4. The trainer only has Docker and uv
Every command in the README must work with only those two. No `psql` installed on the host: use `docker compose exec postgres psql ...` inside scripts. Python scripts run with `uv run`.

## Step I-1 — `compose.yml`
- First line: `name: food-delivery`, so the project name is the same from the host and from the dev container.
- Services: `postgres` (official image), `mongo` (official image, root user from `.env`), `redis` (with `--requirepass ${REDIS_PASSWORD}`), `api` (built from your `Dockerfile`).
- Ports published on `127.0.0.1` only: 5432, 27017, 6379, 8000.
- **Healthchecks** on the three databases (`pg_isready`, `mongosh --eval "db.adminCommand('ping')"`, `redis-cli -a ... ping`), and `api` with `depends_on: condition: service_healthy`.
- Named volumes for the data.
- Every password through `${...}` from `.env`. Nothing written in the file.
- PostgreSQL with statement logging available for the cache evidence (for example `command: postgres -c log_statement=${PG_LOG_STATEMENT:-none}`).
- Redis persistence settings (for example `--appendonly yes`), which you document in `redis.md`.
- `dbgate` in profile `tools` (the snippet is in `CLAUDE.md`).
- ✅ **Done when:** `docker compose up -d` starts everything, the three databases show `healthy`, and DbGate does **not** start unless you pass `--profile tools`.

## Step I-2 — `.env.example`, `.gitignore`, `pyproject.toml`, `Dockerfile`
- `.env.example` with **every** variable from `CLAUDE.md`, all with `CHANGE_ME`.
- `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`.
- `uv init`, then the `uv add` commands from `CLAUDE.md`. Commit `uv.lock`.
- `Dockerfile` based on a uv Python 3.12 image: copy `pyproject.toml` + `uv.lock`, `uv sync --frozen`, copy the code, run `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- ✅ **Done when:** `git status` never shows `.env`, and the `api` image builds.

## Step I-3 — `app/` base
- `app/config.py`: `Settings` with `pydantic-settings` reading every variable.
- `app/db/postgres.py`: engine with `DATABASE_URL`, `pool_size=20, max_overflow=60`, `SessionLocal`, and the `MetaData(naming_convention=...)` + `Base` that every model uses.
- `app/db/mongo.py`: `MongoClient(MONGO_URL)` and the database.
- `app/db/redis.py`: client with `REDIS_URL`, `decode_responses=True`, and a place where Lua scripts are registered.
- `app/errors.py`: `NotFound` → 404, `Conflict` → 409, plus a handler that turns `IntegrityError` into 409.
- `app/main.py`: FastAPI app, a `GET /health` that pings the three databases, the routers included.
- ✅ **Done when:** `http://127.0.0.1:8000/health` answers OK and `/docs` opens.

## Step I-4 — `scripts/setup.sh`
In this order (it is what the README asks):
1. **As `postgres`:** create the `food_delivery` database, the roles `fd_owner`, `fd_app`, `fd_readonly` with passwords from `.env`, `CREATE EXTENSION IF NOT EXISTS btree_gist`.
2. **As `fd_owner`:** `uv run alembic -c postgres/alembic.ini upgrade head`.
3. **As Mongo root:** `uv run python mongodb/setup.py`.

Use `set -euo pipefail` so it stops at the first error.
- ✅ **Done when:** it runs twice in a row with no errors.

## Step I-5 — Alembic + grants migration
- `postgres/alembic.ini` with `script_location = postgres/migrations`.
- `postgres/migrations/env.py`: reads **`MIGRATION_DATABASE_URL`** (never `DATABASE_URL`), imports `Base.metadata` from `app/db/postgres.py` and every model.
- First migration (`op.execute`):
  - `GRANT USAGE ON SCHEMA public TO fd_app, fd_readonly;`
  - `ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fd_app;`
  - `ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO fd_app;`
  - `ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner IN SCHEMA public GRANT SELECT ON TABLES TO fd_readonly;`
  - and a `downgrade()` that undoes them.
- ✅ **Done when:** a table created later by B or C can be read by `fd_app` without any extra grant, and `fd_app` cannot `CREATE TABLE`.

## Step I-6 — `mongodb/setup.py` base
- Connects with `MONGO_ROOT_URL`.
- Creates the user `fd_app` in `food_delivery` with `readWrite` on `food_delivery` only (skip if it exists, or update its password).
- A helper `ensure_collection(name, validator, indexes)` that creates the collection or runs `collMod`, always with `validationLevel: "strict"` and `validationAction: "error"`, then creates the indexes. B and C call this helper for their collections.
- ✅ **Done when:** it runs twice with no errors, and `fd_app` can write to `food_delivery` but not to `admin`.

## Step I-7 — Skeletons for the others
- `redis/rebuild.py`: connects, has one function per key family (empty for now; B and C fill theirs), calls them all.
- `redis/verify.py`: same shape, collects differences, `sys.exit(1)` if any, else `sys.exit(0)`.
- `tests/concurrency/`: empty folder; C writes `run.py`.
- `scripts/seed.sh`: calls the seed steps in order (C's PG seed → B's → yours → C's ratings → Mongo seed → `export_reports.py` → `redis/rebuild.py`). Each step can be a placeholder until its owner writes it.
- ✅ **Done when:** from a clean clone, `cp .env.example .env && docker compose up -d && ./scripts/setup.sh && ./scripts/seed.sh` runs end to end (even with an almost empty seed).

## Step I-8 — Dev container (optional, for the group)
`.devcontainer/devcontainer.json` and `.devcontainer/compose.devcontainer.yml` are already written. They add a `workspace` container (Python 3.12, uv, Docker CLI, editor extensions) next to the three databases. Your job is to make them work with your `compose.yml`:
- the three databases need **healthchecks** (the workspace waits for them);
- the variable names in `compose.devcontainer.yml` must match your `.env.example`;
- test it: VS Code → "Dev Containers: Reopen in Container" → in the terminal, `./scripts/setup.sh`, `./scripts/seed.sh`, `uv run uvicorn app.main:app --host 0.0.0.0 --reload` → `http://127.0.0.1:8000/docs` opens.
- Nothing may depend on it: the README commands on the host must keep working without it.
- ✅ **Done when:** B and C can open the repo in the dev container and run the API without installing anything else.

## Step I-9 — README "how to run"
Write the clean-clone section of `README.md`: the 4 commands, the concurrency test command, the DbGate note, the optional dev container, and the stack with the reason. Keep it updated as the project grows.

---

# Part 2 — Couriers and offers

## Understand these 5 ideas first

### 1. Redis GEO: a map in memory
`GEOADD fd:couriers:geo <lng> <lat> <courier_id>` puts the courier on a map. `GEOSEARCH fd:couriers:geo FROMLONLAT <lng> <lat> BYRADIUS 3 km ASC` returns who is within 3 km, closest first. It is very fast, which is why it lives in Redis and not in PostgreSQL.

### 2. Being online = a key that expires
A member of a GEO set cannot expire on its own. So every time a position arrives, you also run `SET fd:courier:{id}:online 1 EX 30`. If the courier stops sending positions for 30 seconds, the key disappears by itself and they are offline. When you search for couriers, you filter the `GEOSEARCH` results by those who still have that key.

### 3. The TTL always goes with the write
Never `SET` and then `EXPIRE` in two commands: if the app dies between them, the key stays forever. Use `SET ... EX 30` in one command. To do the `GEOADD` and the `SET` together, use a **Lua script**: Redis runs it all at once, with nothing in between.

### 4. "Exactly one wins": the lock and the unique
In F4, inside one transaction:
```
SELECT ... FROM delivery_offers WHERE id = :offer FOR UPDATE;   -- lock the offer
SELECT ... FROM orders WHERE id = :order FOR UPDATE;            -- lock the order
-- is the offer still pending and under 45 s old? does the order still have no courier?
INSERT INTO deliveries (order_id, courier_id, ...)              -- UNIQUE (order_id)
UPDATE delivery_offers SET outcome = 'withdrawn' WHERE order_id = :order AND id <> :offer AND outcome = 'pending';
```
The `FOR UPDATE` on the order makes the 50 requests go through this block **one at a time**. The first one wins. The others, when they get there, see the order already has a courier and get a 409. The `UNIQUE (order_id)` on `deliveries` is PostgreSQL's final guarantee: even if the app has a bug, two deliveries for the same order can never exist.

### 5. Offers that expire "lazily"
You do not need anything running every second to mark offers as expired. An offer is valid if it is `pending` **and** its `sent_at` is less than 45 s ago. When someone reads it, or the order is offered again, you mark as `expired` the ones that ran out of time. The brief explicitly allows this.

## Step C-1 — Couriers migration
- `couriers`: name, email `UNIQUE`, phone `UNIQUE`, `vehicle_type` (`bicycle`/`scooter`/`car`), `licence_plate` `UNIQUE`, `status` (`active`/`blocked`).
- A multi-column `CHECK`, for example: `(vehicle_type = 'bicycle' AND licence_plate IS NULL) OR (vehicle_type <> 'bicycle' AND licence_plate IS NOT NULL)`.
- ✅ **Done when:** inserting a bicycle with a plate, or a car without one, is refused by PostgreSQL.

## Step C-2 — F7: online, position, offline
- `POST /couriers/{id}/online` and `POST /couriers/{id}/position` (lng, lat): a Lua script in `redis/scripts/` that does `GEOADD` + `SET ... EX 30` at once. Then insert a document into `courier_positions` in Mongo, with the order if they are on a delivery.
- `POST /couriers/{id}/offline`: `ZREM` from the geo set + `DEL` the online key.
- A `blocked` courier → 409.
- ✅ **Done when:** you send a position, see the courier with `GEOSEARCH` in `redis-cli`, wait 30 s, and the online key is gone.

## Step C-3 — `courier_positions` collection in Mongo
- In `mongodb/setup.py`, with your `ensure_collection` helper: `$jsonSchema` validator (`courier_id`, `location` as a GeoJSON Point, `recorded_at` as a date, optional `order_id`), `strict` + `error`.
- TTL index on `recorded_at` with `expireAfterSeconds: 604800` (7 days) and an index `{courier_id: 1, recorded_at: -1}`.
- Also the `explain("executionStats")` without and with that index (the README asks for at least one).
- ✅ **Done when:** a document without `courier_id` is refused and `getIndexes()` shows the TTL.

## Step C-4 — Offers and deliveries migration
- `delivery_offers`: order, courier, `sent_at timestamptz`, `outcome` (`pending`/`accepted`/`rejected`/`expired`/`withdrawn`) with a `CHECK`, and `UNIQUE (order_id, courier_id)` so the same offer is not repeated.
- `deliveries`: order with **`UNIQUE (order_id)`**, courier, `accepted_at`, `picked_up_at`, `delivered_at`, `distance_km` with `CHECK >= 0`. B fills the last three in F5.
- Index for "a courier's active deliveries" (`EXPLAIN` query 4).
- ✅ **Done when:** two `deliveries` for the same order are refused.

## Step C-5 — F3: restaurant accepts, rejects, reoffers
- `POST /restaurants/{id}/orders/{order_id}/accept`:
  1. In the transaction: `FOR UPDATE` on the order, must be `placed`, becomes `accepted`, history. (If B does the kitchen capacity extension, it goes here.)
  2. `GEOSEARCH` 3 km around the restaurant → keep those with `fd:courier:{id}:online` → keep in PG those who still have room (bicycle 1, scooter 2, car 3) → the first 5.
  3. Insert the offers in PG (`pending`) and `fd:offer:{id}` in Redis with `EX 45`.
- `POST .../reject`: `placed → rejected` (giving the stock back is B's function; call it).
- `POST /restaurants/{id}/orders/{order_id}/reoffer` and `POST /backoffice/orders/{order_id}/reoffer`: mark old offers as `expired` and offer to the next couriers who have not received it yet.
- ✅ **Done when:** with 3 couriers online nearby, accepting an order creates 3 offers.

## Step C-6 — F4: courier accepts (real version)
`POST /couriers/{id}/offers/{offer_id}/accept`, with the transaction from idea 4:
- Offer is not this courier's → 404.
- Offer not `pending`, or 45 s passed, or the order already has a courier → 409 (and mark it `expired` if that is the case).
- Otherwise: insert the delivery, offer `accepted`, the others `withdrawn`, delete that order's `fd:offer:*` keys, update tracking (C's function).
- Catch the unique's `IntegrityError` and return 409, never 500.
- ✅ **Done when:** two couriers accepting the same order get one 200 and one 409.

## Step C-7 — F4 naive version
With `?mode=naive` (and only if `ENABLE_NAIVE_MODE=true`): read whether the order has a courier, check in Python, and insert. No `FOR UPDATE`.
- ✅ **Done when:** the same order test in naive mode gives more than 1 success, or 500 errors (from the unique).

## Step C-8 — "Same order" concurrency scenario
- **Fixture:** delete what is left and create 1 `accepted` order, 50 `active` online couriers and 50 `pending` offers (one each, just sent). The limit of 5 offers does not apply here.
- **Attack:** 50 `POST /couriers/{id}/offers/{offer_id}/accept` at the same time.
- **Check in PG:** exactly 1 row in `deliveries` for that order.
- This test does **not** need F3 or F7 working, because the fixture creates everything directly. You can do it early.
- ✅ **Done when:** real mode gives 1 success, 49 × 409, 0 × 500, three times in a row, and naive mode breaks.

## Step C-9 — Seed
- 2,500 couriers with a mix of vehicles (plates must be unique and respect the `CHECK`).
- Offers: ~1.5 per delivered order (some `expired`/`rejected`/`withdrawn`, one `accepted`).
- Deliveries for orders that reached `picked_up` or `delivered`, with realistic distances.
- Mongo: **≥50k** positions in the last 7 days (dates relative to today, or the TTL deletes them straight away).
- Runs after B's seed (you need the orders).
- ✅ **Done when:** correct counts and no constraint turned off.

## Step C-10 — Extension (if there is time): vehicle limit (rule 3)
A scooter with 1 delivery accepts two offers at the same time, and both requests see "1 < 2"; it ends up with 3 deliveries. This is a **write skew**: each request writes to a different row, so there is no direct conflict between them. Fix: `SELECT ... FROM couriers WHERE id = :c FOR UPDATE` before counting active deliveries. Now the two requests queue up. Add it as a third scenario in `run.py`.

## Step C-11 — Documentation (English)
- `README.md`: the "how to run" section (from Part 1).
- `docs/redis.md`: **every** key in the project (yours, plus B's stock and C's tracking and ranking, who give you the details): structure, example, TTL and why, commands, class (truth, derived or ephemeral). The persistence and memory settings. The cache evidence that C produces.
- `docs/concurrency.md`: the F4 mechanism and 6 outputs (same order, 2 modes × 3 runs). B owns the file; you write your section.
- `docs/postgres.md`: your tables, the roles and grants, and the `EXPLAIN` for query 4. B owns the file; you write your section.
- `docs/runbook.md`: the Redis section. Defend whether you back it up or only rebuild: positions and pending offers are ephemeral; stock and tracking are rebuilt from PG and Mongo.

---

## Who you depend on

| You need… | From | For |
|---|---|---|
| `orders` table and working F2 | B | Steps C-4 and C-5 |
| Function that gives stock back on reject | B | Step C-5 |
| Restaurant coordinates | C | Step C-5 (centre of the 3 km search) |
| Tracking function | C | Step C-6 |
| Details of their Redis keys | B and C | `redis.md` |

| They need you… | Who | For |
|---|---|---|
| **The whole infrastructure** | B and C | Everything. That is why you start first. |
| `ensure_collection` helper | B and C | Their Mongo collections |
| `deliveries` table | B | F5 picked_up / delivered |
| Courier positions in Redis | C | F6 tracking |
| `deliveries` and offers with dates | C | Report export |

---

## Questions the trainer may ask you

- **"Why does the app have a different role from the migrations?"**
  Least privilege. `fd_app` can read and write data but cannot create or drop tables, nor change the history. If the app has a bug or an injection, the damage is limited.
- **"What is `ALTER DEFAULT PRIVILEGES` for?"**
  So that every table created later by `fd_owner` automatically gets the grants for `fd_app` and `fd_readonly`.
- **"Why can't roles be created in a migration?"**
  Creating roles needs a superuser, and migrations run as `fd_owner`. So it is step 1 of `setup.sh`.
- **"How do you make sure the passwords are not in Git?"**
  `.env` is in `.gitignore`, `compose.yml` only uses `${...}`, `.env.example` only has `CHANGE_ME`. And `git log -p | grep -i password` shows nothing real.
- **"50 couriers accept at the same time. What happens, step by step?"**
  All 50 try the `FOR UPDATE` on the order. One gets it, the other 49 wait. The first inserts the delivery and commits. The next one wakes up, sees the order already has a courier, and gets 409. And so on.
- **"What if the app has a bug and does not lock?"**
  The `UNIQUE (order_id)` on `deliveries` refuses the second delivery. PostgreSQL is the last line of defence.
- **"Why is online presence not in PostgreSQL?"**
  It changes every few seconds for 2,500 couriers and has to expire by itself. Redis does that with `EX 30`, and PostgreSQL is not flooded with writes.
- **"What is lost if Redis disappears?"**
  Current positions and who is online. It recovers by itself in seconds, when couriers send their next position. Offers are recorded in PG, so nothing important is lost.
- **"Why don't you need a worker to expire offers?"**
  Validity is computed as `sent_at + 45 s` when the offer is read. The `expired` state is written at that moment.
- **"What is a write skew?"**
  Two requests read the same information, decide all is fine, and write to different rows. Neither sees the other's write and the rule breaks. You fix it by locking a shared row, here the courier.

You must also be able to answer questions about B's and C's parts. Ask them to walk you through them.
