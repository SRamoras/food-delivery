# CLAUDE.md — Project B: Food delivery

Context for AI assistants working in this repository. Read this before writing code, schema or docs.
The full rules are in `planning/course-rules.md` (the module's group project rules, copied from the module repo) and `planning/b-food-delivery.md` (the business brief). If this file disagrees with them, they win; point out the conflict instead of guessing.

Two different READMEs: "the course rules" means `planning/course-rules.md`. `README.md` in the repo root is **this project's** README (what it does, how to run it, ER diagram, endpoints, authors table), which the course rules ask us to write.

## What this project is

Group project (3 students) for a databases module. We build the databases and a small backend (no frontend, no auth) for a food delivery business in Portuguese cities: customers order from restaurants, couriers deliver, the back office reads reports.

- **PostgreSQL**: source of truth for everything that must never be lost or contradict itself.
- **MongoDB**: courier position trail (TTL 7 days) and derived report collections.
- **Redis**: real-time state: courier positions and presence, pending offers (45 s), tracking cache, daily stock during the day, rankings.

The technical focus is **concurrency**. These rules must hold under simultaneous requests:

1. An order is assigned to exactly one courier.
2. An item's daily stock never goes below zero.
3. A courier never has more active deliveries than the vehicle allows (bicycle 1, scooter 2, car 3). This is a write skew.
4. A restaurant never has more orders in preparation than its kitchen capacity.

**All four rules must be enforced** (rules 3 and 4 are in the brief's "may be enforced in PostgreSQL or in the app" list: the app is allowed, skipping them is not). The concurrency **test scenarios** are mandatory for rules 1 and 2; scenarios for rules 3 and 4 are the extension.

## Who owns what

| Person | Slice |
|---|---|
| **A** (SRamoras) | All infrastructure (Docker Compose, uv, setup/seed scripts, connections, Alembic setup) + couriers and offers (F3, F4, F7, scenario "same order"), the hardest part |
| **B** (RodrigoDias123) | Orders and daily stock (F2, all of F5, scenario "last portions") |
| **C** (jcleberfernandes) | Catalogue, tracking and reports (F1, F6, F8, report export, all report pipelines but one, shared concurrency script) |

Details in `planning/PLAN.md` and each person's file: `planning/SRamoras-*.md`, `planning/RodrigoDias123-*.md`, `planning/jcleberfernandes-*.md`. Do not write code in another person's slice unless that person asked for it.

---

## Stack (fixed: do not propose alternatives)

| Concern | Tool |
|---|---|
| Language | Python 3.12 |
| Package / env manager | **uv** (`pyproject.toml` + `uv.lock` at the repo root) |
| API | **FastAPI** + Uvicorn |
| Settings | `pydantic-settings` (reads `.env`) |
| Validation | Pydantic v2 |
| PostgreSQL ORM | **SQLAlchemy 2.0** (typed `Mapped[]` models, `select()` style), **sync** sessions |
| PostgreSQL driver | **psycopg 3** (`postgresql+psycopg://...`) |
| Migrations | **Alembic** |
| MongoDB | **pymongo** (sync) |
| Redis | **redis-py** (sync), Lua scripts via `register_script` |
| Concurrency test client | **httpx** `AsyncClient` + `asyncio.gather` |
| Tests / lint | pytest, ruff |
| Runtime | Docker Compose: `postgres`, `mongo`, `redis`, `api` |
| DB client (development only) | **DbGate** in Compose, profile `tools` (see DbGate section) |

Why sync and not async: FastAPI runs `def` endpoints in a thread pool, so concurrent requests still hit the database at the same time (which is what the concurrency tests need). Sync code is simpler to read and to explain in the oral discussion. Do not mix async drivers in.

Dependencies:

```bash
uv add fastapi "uvicorn[standard]" "sqlalchemy>=2.0" "psycopg[binary]" alembic pydantic-settings pymongo redis httpx
uv add --dev pytest ruff
```

---

## Repository layout

The top-level folders are required by the course. Do not move them.

```
compose.yml                   postgres, mongo, redis, api (+ dbgate in profile tools); top-level name: food-delivery
.devcontainer/                optional dev environment (VS Code / Codespaces): devcontainer.json + compose.devcontainer.yml
Dockerfile                    api image, built with uv
pyproject.toml / uv.lock
.env.example                  placeholders only
.gitignore                    .env, .venv/, __pycache__/, *.pyc, .pytest_cache/, .ruff_cache/, .DS_Store
README.md
CLAUDE.md
planning/                     internal group planning (not graded docs): PLAN.md, one file per member,
                              course-rules.md and b-food-delivery.md (copies of the trainer's files)

app/
  main.py                     FastAPI app, routers, exception handlers
  config.py                   Settings (pydantic-settings)
  db/
    postgres.py               engine + SessionLocal (DATABASE_URL, app role)
    mongo.py                  MongoClient (MONGO_URL, readWrite user)
    redis.py                  Redis client (REDIS_URL with password) + loaded Lua scripts
  models/                     SQLAlchemy models (one file per area: geo, customers, restaurants, menu, couriers, orders, offers, payments, ratings)
  schemas/                    Pydantic request/response models
  routers/                    customers, restaurants, couriers, orders, offers, tracking, reports, backoffice
  services/                   business logic and transactions (routers stay thin)
  errors.py                   domain exceptions → HTTP status

postgres/
  alembic.ini
  migrations/                 Alembic env.py + versions/
  sql/                        EXPLAIN queries, helper SQL
  seed/                       PostgreSQL seed (COPY-based)

mongodb/
  setup.py                    user, collections, $jsonSchema validators, indexes (idempotent)
  export_reports.py           reads PG with READONLY_DATABASE_URL, writes report collections
  pipelines/                  one file per report pipeline
  seed.py                     courier position trail seed

redis/
  scripts/                    *.lua
  rebuild.py                  rebuilds every derived key from PG/Mongo
  verify.py                   compares Redis with sources, exit 1 on mismatch

scripts/
  setup.sh                    superuser: db, roles, extensions → owner: alembic upgrade → mongo root: setup.py
  seed.sh                     PG seed → Mongo seed → export_reports → redis rebuild

tests/
  concurrency/run.py          concurrency scenarios (naive and real modes)

docs/
  postgres.md  mongodb.md  redis.md  architecture.md  concurrency.md  runbook.md  ai-usage.md
```

## Common commands

```bash
# from a clean clone
cp .env.example .env
docker compose up -d
./scripts/setup.sh
./scripts/seed.sh

# migrations (always as the owner role, via MIGRATION_DATABASE_URL)
uv run alembic -c postgres/alembic.ini revision -m "add orders"
uv run alembic -c postgres/alembic.ini upgrade head
uv run alembic -c postgres/alembic.ini downgrade -1

# api locally (engines in Docker, ports on 127.0.0.1)
uv run uvicorn app.main:app --reload

# concurrency test
uv run python tests/concurrency/run.py --scenario same-order --mode real
uv run python tests/concurrency/run.py --scenario last-portions --mode naive

# redis
uv run python redis/rebuild.py
uv run python redis/verify.py

# lint / tests
uv run ruff check . && uv run ruff format --check .
uv run pytest

# DbGate (optional, development only) → http://127.0.0.1:3000
docker compose --profile tools up -d dbgate
docker compose --profile tools stop dbgate
```

OpenAPI docs: `http://127.0.0.1:8000/docs`.

## Environment variables (`.env.example`)

```
POSTGRES_SUPERUSER_URL=postgresql+psycopg://postgres:CHANGE_ME@127.0.0.1:5432/postgres
MIGRATION_DATABASE_URL=postgresql+psycopg://fd_owner:CHANGE_ME@127.0.0.1:5432/food_delivery
DATABASE_URL=postgresql+psycopg://fd_app:CHANGE_ME@127.0.0.1:5432/food_delivery
READONLY_DATABASE_URL=postgresql+psycopg://fd_readonly:CHANGE_ME@127.0.0.1:5432/food_delivery
MONGO_ROOT_URL=mongodb://root:CHANGE_ME@127.0.0.1:27017/?authSource=admin
MONGO_URL=mongodb://fd_app:CHANGE_ME@127.0.0.1:27017/food_delivery?authSource=food_delivery
REDIS_URL=redis://:CHANGE_ME@127.0.0.1:6379/0
ENABLE_NAIVE_MODE=true

# plain passwords, for compose.yml (official images, requirepass, DbGate) and setup.sh
POSTGRES_PASSWORD=CHANGE_ME
FD_OWNER_PASSWORD=CHANGE_ME
FD_APP_PASSWORD=CHANGE_ME
FD_READONLY_PASSWORD=CHANGE_ME
MONGO_ROOT_PASSWORD=CHANGE_ME
MONGO_APP_PASSWORD=CHANGE_ME
REDIS_PASSWORD=CHANGE_ME
```

Inside Docker, services use their service names (`postgres`, `mongo`, `redis`) instead of `127.0.0.1`. The passwords in the URLs and in the plain variables must match.

- `ENABLE_NAIVE_MODE`: turns the `?mode=naive` code paths on or off. They exist only to show the race in the concurrency test and the demo.
- `authSource=food_delivery`: `fd_app` is created inside the `food_delivery` database by `mongodb/setup.py`, so it authenticates there. The root user lives in `admin`.

## DbGate (development tool)

DbGate is a GUI client for PostgreSQL, MongoDB and Redis, used only to inspect data during development.

- It is in `compose.yml` under the **`tools` profile**: `docker compose up -d` from a clean clone does **not** start it, so it does not slow down or change what the trainer runs.
- **The app, scripts and tests never depend on it.** Never add `depends_on: dbgate` to anything or use DbGate in any README step.
- In PostgreSQL it connects as **`fd_readonly`**, so nobody changes data by accident. Never as `postgres`.
- Passwords come from `.env` through interpolation (`${...}`), never written in `compose.yml`.
- The port is published on `127.0.0.1` only.
- It does not replace the required evidence: `EXPLAIN (ANALYZE, BUFFERS)`, `explain("executionStats")` and Redis `MONITOR` go into `docs/` as text, taken with `psql`, `mongosh` and `redis-cli`.

Service in `compose.yml`:

```yaml
  dbgate:
    image: dbgate/dbgate
    profiles: ["tools"]
    ports:
      - "127.0.0.1:3000:3000"
    depends_on: [postgres, mongo, redis]
    environment:
      CONNECTIONS: pg,mongo,redis

      LABEL_pg: PostgreSQL (read-only)
      SERVER_pg: postgres
      PORT_pg: 5432
      USER_pg: fd_readonly
      PASSWORD_pg: ${FD_READONLY_PASSWORD}
      DATABASE_pg: food_delivery
      ENGINE_pg: postgres@dbgate-plugin-postgres

      LABEL_mongo: MongoDB
      URL_mongo: mongodb://fd_app:${MONGO_APP_PASSWORD}@mongo:27017/food_delivery?authSource=food_delivery
      ENGINE_mongo: mongo@dbgate-plugin-mongo

      LABEL_redis: Redis
      SERVER_redis: redis
      PORT_redis: 6379
      PASSWORD_redis: ${REDIS_PASSWORD}
      ENGINE_redis: redis@dbgate-plugin-redis
```

## Dev container (optional)

`.devcontainer/` opens the repo in VS Code or Codespaces inside a container with Python 3.12, uv, the Docker CLI and the editor extensions, next to the three databases from `compose.yml`.

- `compose.devcontainer.yml` adds a `workspace` service and overrides the connection URLs to use service names (`postgres`, `mongo`, `redis`) with the passwords from `.env`.
- `postCreateCommand` installs uv and runs `uv sync`.
- The Docker CLI talks to the host's Docker (`docker-outside-of-docker`), so `scripts/setup.sh` and `scripts/seed.sh` work from inside.
- `compose.yml` has `name: food-delivery` at the top, so `docker compose exec ...` finds the same containers from inside and outside the dev container.
- **Nothing may depend on it.** The README commands (Docker + uv on the host) are what the trainer runs and must keep working without it.

---

## Coding conventions

### General
- **Every query is parameterised.** SQLAlchemy expressions, or `text("... :param")` with bound parameters. MongoDB filters are dicts built from typed values. **Never** f-strings or string concatenation with request input, in SQL, Mongo, or Redis keys built from unvalidated strings.
- **No secrets in Git.** Everything sensitive comes from `Settings`. A password committed once counts forever. Never remove `.env` from `.gitignore`, never `git add -f .env`, and check `git status` before every commit.
- The app connects as `fd_app` (PG), the `readWrite` Mongo user and with the Redis password. Never as `postgres` or `root`.
- **Time:** `from zoneinfo import ZoneInfo; LISBON = ZoneInfo("Europe/Lisbon")`. "Today", day of week, opening hours and the midnight stock reset use Lisbon time. Store moments as `timestamptz` and keep Python datetimes timezone-aware (never naive `datetime.now()`).
- **Money:** `Decimal` in Python, `numeric(10,2)` in PG. Never `float`.
- **Who is acting:** the actor id goes **in the path**, one prefix per actor type, used everywhere:
  - `/customers/{customer_id}/...`
  - `/restaurants/{restaurant_id}/...`
  - `/couriers/{courier_id}/...`
  - `/backoffice/...` (no id)
- Type hints everywhere. Routers are thin: parse input, call a service, map the result. Business rules live in `app/services/`.
- Code, comments, `README.md` and everything in `docs/` are in **English**.

### Docstrings and comments
- Every module starts with a **one-line docstring** saying what the file is for (as in `app/config.py` and `app/db/*.py`).
- **Services and other non-trivial functions** get a short docstring: what it does, which business rule it enforces and, for concurrent flows, which lock or conditional update protects it.
- **Router functions** get a one-line docstring: FastAPI shows it as the endpoint description in `/docs`, which is how every endpoint gets documented.
- **Comments explain why, not what:** the reason for a lock, a TTL, a pool size, a constraint, an `ON DELETE`. Never `# increment i`.
- **No docstrings on trivial code:** Pydantic schemas whose fields speak for themselves, one-line helpers, routers that only call a service (beyond the one line above).
- Keep them short (1–3 lines). Use the Google style (`Args:` / `Returns:` / `Raises:`) only when the arguments really need explaining.
- Docstrings and comments must stay true: when the code changes, update them in the same commit.

### HTTP status codes
| Case | Status |
|---|---|
| Created | 201 |
| OK | 200 |
| Not found | 404 |
| Invalid input (Pydantic) | 422 |
| Refused by a business rule (stock, already taken, capacity, invalid transition, closed, below minimum, zone not delivered, payment declined) | **409** with `{"detail": "<reason>"}` |

A request must never return 5xx because of a business rule. In real mode, a 5xx fails the concurrency test.

`IntegrityError`: in **real mode**, catch it explicitly in the service, only where a constraint backs a rule (for example the `UNIQUE (order_id)` on `deliveries`), and raise `Conflict` (409). There is **no global `IntegrityError` handler**: in naive mode the violation must surface as a 5xx so the concurrency test shows the race, and an unexpected violation (a bug, such as a missing `NOT NULL` value) must stay visible as a 500 instead of looking like a normal 409.

### SQLAlchemy
- SQLAlchemy 2.0 style: `Mapped[...]`, `mapped_column`, `select()`, `session.execute(...)`. No legacy `session.query`.
- One transaction per request: `with SessionLocal() as session, session.begin(): ...`.
- `MetaData(naming_convention=...)` so constraint names are stable in migrations (e.g. `ck_%(table_name)s_%(constraint_name)s`, `uq_...`, `fk_...`, `ix_...`).
- Pool: `pool_size=20, max_overflow=60` so the 60-request concurrency test does not queue on connections.
- Locks: `select(...).with_for_update()`; isolation when needed: `session.connection(execution_options={"isolation_level": "SERIALIZABLE"})`, with retry on serialization failure.

### Alembic
- `postgres/migrations/env.py` reads **`MIGRATION_DATABASE_URL`**, never `DATABASE_URL`.
- Autogenerate is allowed for tables, but **always review and edit** the result. Everything the ORM does not express goes in `op.execute(...)` in the migration: multi-column `CHECK`, `EXCLUDE`, partial unique indexes, triggers, `REVOKE`, `GRANT`, `ALTER DEFAULT PRIVILEGES`.
- Every migration has a working `downgrade()`.
- Never `Base.metadata.create_all()`.
- Extensions and roles are created in `scripts/setup.sh` by the superuser, not in migrations. We need `btree_gist` (for the `EXCLUDE` on opening hours). `pg_trgm` only if we add a text-search feature; do not create extensions we do not use.
- Migrations form one chain: always `git pull` before creating a revision; if two heads appear, fix with `alembic merge`.

### MongoDB
- `mongodb/setup.py` is idempotent: create a collection if it is missing, otherwise `collMod` the validator; `create_index` is safe to repeat.
- Every collection: `$jsonSchema` validator, `validationLevel: "strict"`, `validationAction: "error"`.
- Use `datetime` (BSON date) for times, so TTL indexes work.

### Redis
- Key prefix **`fd:`**. Every key pattern is documented in `docs/redis.md` (structure, example, TTL + reason, commands, class).
- **TTL is set in the same command as the write** (`SET key val EX n`), or in the same `MULTI/EXEC` / Lua script. Never a separate `EXPIRE` after the write.
- **Never `KEYS`** in app code. Use `SCAN` in scripts.
- Multi-step atomic operations go in Lua scripts in `redis/scripts/`, loaded once in `app/db/redis.py`.

---

## Domain rules

### Must be enforced by PostgreSQL itself
- At most one courier assigned per order (unique on the delivery's `order_id`).
- Item daily stock never negative (`CHECK (remaining >= 0)`).
- No overlapping opening periods for the same restaurant and weekday (`EXCLUDE USING gist` with `btree_gist`, on `restaurant_id WITH =, weekday WITH =, hours WITH &&`; 24:00 must be representable).
- At most one default address per customer (partial unique index `WHERE is_default`).
- Licence plate present for scooter/car, absent for bicycle (multi-column `CHECK`).
- Ranges: prices, fees, tips, totals ≥ 0; quantity ≥ 1; ratings 1–5.
- Uniques: zone name per city, fee per (restaurant zone, customer zone), customer email and phone, restaurant NIF, courier email, phone and plate, payment provider reference, one rating per order.
- NIF `CHECK (nif ~ '^[0-9]{9}$')`; statuses, vehicle types and payment methods restricted by `CHECK`.
- Status history is append-only: `REVOKE UPDATE, DELETE ON order_status_history FROM fd_app` in a migration.

### May be enforced in PG or the app (record the choice in `docs/postgres.md`)
- Allowed status transitions.
- Kitchen capacity.
- Maximum active deliveries per vehicle.
- Minimum order value, ordering only within opening hours, ordering only to delivered zones.

### Order status machine
`placed → accepted → preparing → ready → picked_up → delivered`
- `placed → rejected` (restaurant only).
- Any status before `picked_up` → `cancelled` (customer, restaurant or back office, with a reason).
- No other transition. Every change is inserted into the history table (old, new, actor type, actor id, `changed_at`) in the same transaction as the update.
- Rejected or cancelled orders give their portions back to the daily stock. Cancelled orders paid by card or MB WAY get a new `refunded` payment row with the same amount.
- Orders snapshot the delivery address; order lines snapshot the unit price (item + options) and the chosen options (`jsonb`).

### Payments
The place-order body has `simulate: "approved" | "declined"`. If declined, nothing is written except a refusal (409): no order, no stock taken. Cash has no provider reference; card and MB WAY get a generated unique reference.

### Delivery offers
- On accept, offer to up to 5 online couriers within 3 km of the restaurant who have room for another delivery: `GEOSEARCH fd:couriers:geo FROMLONLAT ... BYRADIUS 3 km ASC`, filtered by `EXISTS fd:courier:{id}:online` and by active-delivery count.
- Offers live in PG (record and outcome) **and** in Redis (`fd:offer:{offer_id}` with `EX 45`).
- An offer is valid if PG says `pending` and its `sent_at` is less than 45 s ago. Offers are marked `expired` lazily, when read or when the order is offered again.
- First valid accept wins; all other offers for that order become `withdrawn` in the same transaction. Accepting an expired, withdrawn or taken offer → 409.
- F4 also re-checks the **vehicle limit** with the courier row locked (`FOR UPDATE`): a courier with no room left → 409. F3 filtering by room is not enough, because the courier may have accepted another offer since.
- F3 accept checks the **kitchen capacity** with the restaurant row locked (`FOR UPDATE`): restaurant full → 409.
- A courier can decline an offer: `POST /couriers/{courier_id}/offers/{offer_id}/reject` → outcome `rejected`.
- `POST /restaurants/{restaurant_id}/orders/{order_id}/reoffer` and `POST /backoffice/orders/{order_id}/reoffer` offer the order to the next couriers (not already offered). No worker.

---

## Current design decisions (edit when the group changes them)

| Topic | Decision | Doc |
|---|---|---|
| Item options | `jsonb` column on the menu item, validated by Pydantic; order lines snapshot the chosen options as `jsonb` | justify in `docs/mongodb.md` |
| Daily stock storage | PG table `(item_id, stock_date)` → `remaining`, source of truth; Redis `fd:stock:{item_id}:{date}` is a derived copy for fast reads | `docs/architecture.md` |
| Daily stock reset | **Lazy, no worker**: the row for today (Lisbon date) is created from the configured value on first use (`INSERT ... ON CONFLICT DO NOTHING`), so midnight needs no job | `docs/architecture.md` |
| Rule 2 (stock) | Conditional atomic update in the order transaction: `UPDATE ... SET remaining = remaining - :q WHERE item_id = :id AND stock_date = :today AND remaining >= :q RETURNING remaining`; 0 rows → 409. `CHECK (remaining >= 0)` is the last line of defence | `docs/concurrency.md` |
| Rule 1 (one courier) | In one transaction: lock the offer and the order (`SELECT ... FOR UPDATE`), check validity, insert the delivery (unique `order_id`), mark the offer `accepted` and the others `withdrawn`. Unique violation → 409 | `docs/concurrency.md` |
| Rule 3 (vehicle limit) | Lock the courier row `FOR UPDATE` before counting active deliveries | `docs/concurrency.md` |
| Rule 4 (kitchen capacity) | Lock the restaurant row `FOR UPDATE` before counting orders in `accepted`/`preparing`/`ready` | `docs/concurrency.md` |
| Isolation level | `READ COMMITTED` + explicit row locks / conditional updates | `docs/concurrency.md` |
| Naive mode | Same endpoints with `?mode=naive` (only when `ENABLE_NAIVE_MODE=true`): read-check-write with no locks, to show the race | `docs/concurrency.md` |
| F6 tracking | `fd:order:{id}:track` hash (customer_id, status, courier_id, updated_at), written whenever the status changes (after PG commits); courier position from the geo set. The ownership check (is this the customer's order?) compares with the `customer_id` **in the hash**, never in PG. Cache miss → read PG once and fill the key | `docs/redis.md` |
| Ranking | Per-city, per-minute sorted-set buckets `fd:rank:{city_id}:{yyyymmddHHMM}` (`ZINCRBY`, `EX 3900` in the same `MULTI`), `ZUNION` of the last 60 buckets, top 20 | `docs/redis.md` |

### Redis key patterns (starting point)

| Key | Type | TTL | Class |
|---|---|---|---|
| `fd:couriers:geo` | GEO | none (members removed on offline) | ephemeral |
| `fd:courier:{id}:online` | string | `EX 30`, refreshed on every position | ephemeral |
| `fd:offer:{offer_id}` | hash | `EX 45` | ephemeral (PG is the record) |
| `fd:order:{id}:track` | hash | e.g. `EX 86400` | derived |
| `fd:stock:{item_id}:{yyyy-mm-dd}` | string (int) | `EXAT` next Lisbon midnight + margin | derived |
| `fd:rank:{city_id}:{yyyymmddHHMM}` | ZSET | `EX 3900` | derived |

### MongoDB collections (starting point)

| Collection | Content | Truth or derived | Index |
|---|---|---|---|
| `courier_positions` | one doc per position: courier_id, `location` (GeoJSON Point), `recorded_at`, optional order_id | source of truth for the trail | TTL on `recorded_at` (604800 s), `{courier_id: 1, recorded_at: -1}` |
| `report_orders` | one doc per finished order: zone, city, restaurant, cuisines, lines with options, status timestamps, cancel reason/actor, fee, tip | derived (export) | per pipeline |
| `report_offers` | one doc per offer: order, courier, zone, sent_at, outcome | derived (export) | per pipeline |

Report pipelines to implement (at least 3 of the brief's 6): **1** delivery time per zone and hour, **4** cancellations by reason and actor, **5** restaurant acceptance and preparation times. Add more if there is time.

---

## Concurrency tests (`tests/concurrency/run.py`)

- `--scenario same-order|last-portions` and `--mode naive|real`.
- Naive mode calls the same endpoints with `?mode=naive`. In naive mode the race shows up as broken data or as 5xx from the constraints; that is the point.
- Fixtures reset and create their own state directly in the DB (via `DATABASE_URL`), so the test runs any number of times. Only the contested requests go through the API.
- All contested requests are fired together with `asyncio.gather`.
- Output per scenario: mode, succeeded (2xx), refused (4xx), failed (5xx), whether the rule holds in PG. Exit 1 if the rule is broken, or (real mode) any 5xx; else 0.
- **Same order (F4):** 1 accepted order, 50 online couriers each with a `pending` offer → exactly 1 accepted, 49 refused, PG has exactly one delivery for the order.
- **Last portions (F2):** restaurant open 00:00–24:00 every day, item with stock 30, 60 customers in a delivered zone, all order 1 portion with `simulate=approved` → 30 placed, 30 refused, stock ends at 0.
- `docs/concurrency.md` shows 3 runs per scenario per mode (12 outputs) and explains the isolation level and locks.

## Flows (all mandatory)

| Flow | Endpoint sketch |
|---|---|
| F1 Browse | `GET /customers/{id}/addresses/{address_id}/restaurants` (open now, delivers to the zone, fee, avg rating); `GET /restaurants/{id}/menu` |
| F2 Place order | `POST /customers/{id}/orders` |
| F3 Accept / reject / reoffer | `POST /restaurants/{id}/orders/{order_id}/accept`, `.../reject`, `.../reoffer` |
| F4 Courier accepts | `POST /couriers/{id}/offers/{offer_id}/accept`; decline: `POST /couriers/{id}/offers/{offer_id}/reject` |
| F5 Status updates | `POST /restaurants/{id}/orders/{order_id}/preparing`, `.../ready`; `POST /couriers/{id}/deliveries/{order_id}/picked-up`, `.../delivered`; `POST /customers/{id}/orders/{order_id}/cancel`, `POST /restaurants/{id}/orders/{order_id}/cancel`, `POST /backoffice/orders/{order_id}/cancel` |
| F6 Track | `GET /customers/{id}/orders/{order_id}/track` (Redis only on repeat) |
| F7 Location | `POST /couriers/{id}/online`, `POST /couriers/{id}/position`, `POST /couriers/{id}/offline` |
| F8 Reports | `GET /backoffice/reports/{report_name}` |

## Seed

- Deterministic: `random.seed(42)` (and Faker seeded if used). Dates relative to the run day.
- Respects every constraint; never disable constraints or triggers.
- Realistic skew (Pareto/Zipf: a few restaurants, items and customers dominate).
- Bulk load with psycopg `cursor.copy(...)`. Whole seed **under 5 minutes**.
- Volumes: 5 cities × 8–15 zones, 60k customers (1–3 addresses), 1,200 restaurants, ~30k items, 2,500 couriers, ≥400k orders over 12 months, ≥1M order lines, one history row per status reached, ~1.5 offers per delivered order, ratings on ~40% of delivered, ≥50k position docs in the last 7 days. ~5% cancelled, ~2% rejected, with reasons and refunds.

---

## How to help this group

- **Every member must explain every line** in the oral discussion ("the AI wrote it" is not an answer). When you write code, briefly explain the non-obvious parts: why this lock, what happens with two simultaneous requests, why this constraint or index, why this TTL.
- Prefer the simplest correct solution. Favour enforcing rules in PostgreSQL.
- When a change affects a decision above or a doc in `docs/`, say so and propose the text.
- After a significant AI-assisted task, propose an entry for `docs/ai-usage.md`: **Who**, **Tool**, **For what** (files), **Outcome** (kept / changed / rejected and why), **Verification**, **Mistakes caught**.
- Do **not** create commits, add `Co-authored-by` lines, or suggest squash merges. Each member commits their own work with their own email in all four areas (`postgres/`, `mongodb/`, `redis/`, `app/`); formatting-only commits do not count.
- Never weaken a constraint, a test or a TTL rule to make something pass. Fix the cause.

## Deadline

Delivery = highest SemVer tag (e.g. `v1.0.0`) pushed **before session 19 starts**. Go through the delivery checklist at the end of `planning/course-rules.md` first.