# Group plan — Project B: Food delivery

Internal file for the group: who does what, and in what order.
It is not one of the graded documents in `docs/`, and commits to it do not count towards any area.

---

## Rules we cannot forget

- [ ] **Everyone has real commits in all 4 areas:** `postgres/`, `mongodb/`, `redis/`, `app/`. Each missing area costs **−2 points** on the individual mark.
- [ ] We do not split by database engine. We split by **feature** (slices), and every slice touches all 4 areas.
- [ ] Commits in the root, `docs/`, `scripts/` and `tests/` **do not count** towards any area.
- [ ] Merge commits, `Co-authored-by` lines and formatting-only commits **do not count**.
- [ ] **Squash merge is forbidden.** Turn it off in Settings → General → Pull Requests.
- [ ] Never `git push --force` on `main`.
- [ ] Everyone always uses the **same email** in `git config user.email`, the one in the README authors table.
- [ ] No passwords in Git. `.env` is in `.gitignore`.
- [ ] Everyone must be able to **explain the others' code** in session 19.
- [ ] Every relevant use of AI goes into `docs/ai-usage.md`.
- [ ] Delivery: a SemVer tag (e.g. `v1.0.0`) pushed **before session 19 starts**.

---

## Who does what

| | **A — Infrastructure + couriers and offers** | **B — Orders and stock** | **C — Catalogue, tracking and reports** |
|---|---|---|---|
| **GitHub** | SRamoras | RodrigoDias123 | jcleberfernandes |
| **Infrastructure** | **All of it:** Docker Compose, Dockerfile, uv, `.env.example`, `setup.sh`, `seed.sh`, connections in `app/db/`, Alembic setup, roles and grants, `mongodb/setup.py` base, `redis/` script skeletons | — | — |
| **Flows** | F7, F3, F4 | F2, all of F5 (preparing, ready, picked_up, delivered, cancel) | F1, F6, F8 |
| **PostgreSQL** | Grants migration, `couriers`, `delivery_offers`, `deliveries` | `daily_stock`, `orders`, `order_lines`, `payments`, `order_status_history` | `cities`, `zones`, `zone_fees`, `customers`, `customer_addresses`, `restaurants`, cuisines, opening hours, menu, `ratings` |
| **MongoDB** | `setup.py` base (user, `ensure_collection` helper), `courier_positions` collection + TTL | Pipeline 4 (cancellations) | `export_reports.py`, report collections, pipelines 1 (delivery time) and 5 (restaurant times) |
| **Redis** | `redis/` skeletons (rebuild, verify), `fd:couriers:geo`, `fd:courier:*:online`, `fd:offer:*`, position Lua script | `fd:stock:*` | `fd:order:*:track`, `fd:rank:*` |
| **Concurrency** | **Same order** scenario (+ rule 3 if there is time) | **Last portions** scenario (+ rule 4 if there is time) | Shared `tests/concurrency/run.py` (output, exit codes) |
| **Seed** | `seed.sh` orchestration + couriers, offers, deliveries, positions in Mongo | Orders, lines, payments, history, stock | Cities, zones, fees, customers, addresses, restaurants, menu, ratings |
| **Docs** | README "how to run" section, `redis.md` (all keys), F4 section of `concurrency.md`, Redis runbook | Owner of `postgres.md` and `concurrency.md`, PostgreSQL runbook | `architecture.md`, `mongodb.md`, query 1 `EXPLAIN`, MongoDB runbook |

A has the infrastructure and the hardest part (the race for the "Accept" button, Redis GEO, Lua). To balance it, B took all of F5 and owns `postgres.md` and `concurrency.md`, and C took pipeline 1.

---

## Phase 0 — Decide together (before writing code)

- [ ] Create the GitHub repo, add the 3 members, give the trainer read access.
- [ ] Turn off squash merging.
- [ ] Fill in the "Who does what" table.
- [ ] Draw the **ER diagram** (Mermaid) with every table, main columns and FKs.
- [ ] Decide the `ON DELETE` of each FK.
- [ ] Confirm the `CLAUDE.md` decisions: options in `jsonb`, lazy stock reset, actor in the path, `?mode=naive`.
- [ ] Agree on the Redis key convention (`fd:...`).
- [ ] Agree on the shape of the Mongo documents (`courier_positions`, `report_orders`, `report_offers`).
- [ ] Pick the 3 pipelines (proposal: 1, 4 and 5) and the 3 `EXPLAIN` queries (proposal: 1, 2/3 and 4).

## Phase 1 — Infrastructure (A)

Details in `SRamoras-infra-couriers-and-offers.md`.

- [ ] `compose.yml`, `Dockerfile`, `pyproject.toml`, `.env.example`, `.gitignore`.
- [ ] `scripts/setup.sh` and `scripts/seed.sh`.
- [ ] Connections in `app/db/`, `app/config.py`, `app/main.py`.
- [ ] Alembic setup + grants migration.
- [ ] `mongodb/setup.py` base, `redis/rebuild.py` and `redis/verify.py` skeletons, `tests/concurrency/` folder.
- [ ] `.devcontainer/` (optional dev environment) working with `compose.yml`.
- [ ] **Test:** in a clean clone, `cp .env.example .env && docker compose up -d && ./scripts/setup.sh` runs without errors.

While A does this, B and C can work on the ER diagram, their models and their Lua/pipeline drafts.

## Phase 2 — PostgreSQL schema (everyone their own tables)

Alembic migrations form a chain, so we make them **in this order**. Always `git pull` before creating a new revision; if two heads appear, fix it with `alembic merge`.

1. [ ] **A:** grants + `ALTER DEFAULT PRIVILEGES` (part of the infrastructure).
2. [ ] **C:** `cities`, `zones`, `zone_fees`, `customers`, `customer_addresses` (partial index for the default address).
3. [ ] **C:** `restaurants` (NIF), cuisines (N:N), `opening_periods` (`EXCLUDE`), categories, `menu_items` (options `jsonb`).
4. [ ] **A:** `couriers` (plate `CHECK`).
5. [ ] **B:** `daily_stock` (`CHECK remaining >= 0`), `orders`, `order_lines`, `payments`, `order_status_history` (`REVOKE UPDATE, DELETE`).
6. [ ] **A:** `delivery_offers`, `deliveries` (`UNIQUE order_id`).
7. [ ] **C:** `ratings` (`UNIQUE order_id`, `CHECK 1..5`).
8. [ ] **Everyone:** indexes for the frequent queries and FKs, each with a written reason.

- [ ] **Test:** `alembic upgrade head` on an empty database works; `alembic downgrade base` too.

## Phase 3 — Flows (in parallel)

All three can start at the same time. Some flows depend on others (noted in brackets).

**A — Couriers and offers**
- [ ] F7: online, position (`GEOADD` + `SET ... EX 30` + document in Mongo), offline.
- [ ] F3: restaurant accepts → `GEOSEARCH` 3 km → filter online and with room → up to 5 offers (PG + Redis `EX 45`). *(depends on F2)*
- [ ] F3: reject, reoffer.
- [ ] F4: courier accepts → exactly one wins, the others become `withdrawn`, invalid offers → 409.
- [ ] F4 naive mode.
- [ ] *(extension)* Vehicle limit with `FOR UPDATE` on the courier.

**B — Orders and stock**
- [ ] F2: place order with every rule (open, hours, zone, minimum, available, stock, simulated payment, address and price snapshot, history).
- [ ] F2 naive mode (`?mode=naive`).
- [ ] Stock in Redis updated after the commit.
- [ ] F5: preparing, ready, cancel (gives stock back, refund, reason, history).
- [ ] F5: picked_up, delivered (updates `deliveries` and the ranking). *(depends on F4)*
- [ ] Invalid transitions → 409, with one shared transition function A also uses.
- [ ] *(extension)* Kitchen capacity on F3 accept, with `FOR UPDATE` on the restaurant (agree with A where it goes).

**C — Catalogue, tracking, reports**
- [ ] F1: restaurants open now that deliver to the address, with fee and average rating.
- [ ] F1: a restaurant's menu with the options of each item.
- [ ] F6: tracking from Redis (`fd:order:{id}:track` + courier position); only goes to PG when the key is missing. *(depends on F2–F5 writing to Redis)*
- [ ] Ranking of the 20 restaurants with most deliveries in the last hour, per city.
- [ ] F8: reports endpoint that runs the pipelines. *(depends on the export)*

## Phase 4 — Seed

Order in `seed.sh`: **C's PG seed → B's PG seed (orders) → A's PG seed (couriers, offers, deliveries) → C's ratings → Mongo seed → export_reports → Redis rebuild**.

- [ ] `random.seed(42)`, dates relative to today.
- [ ] Volumes: 5 cities × 8–15 zones, 60k customers, 1,200 restaurants, ~30k items, 2,500 couriers, ≥400k orders, ≥1M lines, ~1.5 offers per delivered order, ratings on ~40%, ≥50k positions in the last 7 days.
- [ ] ~5% cancelled, ~2% rejected, with reasons and refunds.
- [ ] Uneven data: some restaurants, items and customers with many more orders.
- [ ] Load with `COPY`; no constraint turned off.
- [ ] **Test:** the full seed runs in **under 5 minutes**.

## Phase 5 — MongoDB and Redis complete

- [ ] Every collection with `$jsonSchema`, `strict`, `error`; `setup.py` can run twice without failing.
- [ ] 7-day TTL on `courier_positions`.
- [ ] `export_reports.py` reads with `fd_readonly` and writes the report collections.
- [ ] 3 pipelines as files in `mongodb/pipelines/`.
- [ ] `explain("executionStats")` of one query, without and with its index.
- [ ] `redis/rebuild.py` rebuilds every derived key.
- [ ] `redis/verify.py` exits 1 when there are differences, 0 when everything matches.
- [ ] **Test:** `FLUSHALL` → `rebuild.py` → `verify.py` exits with 0.

## Phase 6 — Concurrency

- [ ] Fixtures that reset and create the starting state (may write straight to the DB).
- [ ] Contested requests through the **API**, all at the same time (`asyncio.gather`).
- [ ] **Same order:** 50 couriers, 50 offers → real: 1 success, 49 × 409, 0 × 5xx.
- [ ] **Last portions:** 60 customers, stock 30 → real: 30 successes, 30 × 409, 0 × 5xx, stock 0.
- [ ] Naive mode: the rule breaks (more successes than allowed, or 5xx).
- [ ] Output: mode, successes, refusals, 5xx, whether the rule holds; exit 0 or 1.
- [ ] Run each scenario 3 times in each mode and save the **12 outputs**.

## Phase 7 — Documentation

- [ ] `README.md`: what it is, how to run from a clean clone, concurrency test, stack and why, ER diagram, endpoints / OpenAPI link, how the actor is identified, authors table, links to `docs/`.
- [ ] `docs/postgres.md`: tables, constraints, indexes, both lists from the brief, denormalisations, **3 `EXPLAIN` without and with the index**, indexed and non-indexed FKs, roles.
- [ ] `docs/mongodb.md`: each collection (why Mongo, truth or derived, example, validator, embed or reference), where the options live and why, the export, pipelines with output.
- [ ] `docs/redis.md`: each key pattern (structure, example, TTL, commands, class), **cache evidence** (`MONITOR` + PG log), rebuild/verify, persistence.
- [ ] `docs/architecture.md`: source-of-truth table, data flow between engines (sequence diagrams), second-write failures, state that changes with time, security.
- [ ] `docs/concurrency.md`: isolation, locks, why the naive version breaks, 12 outputs.
- [ ] `docs/runbook.md`: per engine — backup, backup and restore commands, verification, justified RTO/RPO, what is lost.
- [ ] `docs/ai-usage.md`: one entry per relevant use + the final declaration with the 3 names.

## Phase 8 — Prepare session 19

- [ ] Each person walks the other two through their slice, file by file.
- [ ] Each person can answer the typical questions about the others' parts:
  - why does this constraint or index exist?
  - what happens with two simultaneous requests here?
  - what is lost if Redis disappears?
  - how do you restore MongoDB?
  - why is this embedded and that referenced?
  - what did the AI get wrong?
- [ ] Rehearse the 10-minute demo from a **clean clone of the tag**: start, naive test, real test, explain the mechanism.
- [ ] If the seed is slow, run it before your slot.

---

## Weekly commit check

Each person runs this with their own email. If a **0** shows up, fix it that week.

```bash
for area in "postgres/" "mongodb/" "redis/" "app/"; do
  printf "%-12s " "$area"
  git log --no-merges --author="your.email@example.com" --oneline -- $area | wc -l
done
```

| Week | A (pg / mongo / redis / app) | B (pg / mongo / redis / app) | C (pg / mongo / redis / app) |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| Delivery | | | |

---

## Final checklist (from the README)

- [ ] Runs from a clean clone with only Docker and uv.
- [ ] All migrations apply to an empty database with the owner role.
- [ ] The seed loads the volumes in under 5 minutes, with constraints on, and runs the export and the rebuild.
- [ ] Every mandatory flow works through the API.
- [ ] Every rule in the "Must be enforced by PostgreSQL" list is in PostgreSQL.
- [ ] `FLUSHALL` → rebuild → verify exits with 0.
- [ ] Cache evidence in `docs/redis.md`.
- [ ] 3 pipelines run, with output in `docs/mongodb.md`.
- [ ] 3 queries with `EXPLAIN (ANALYZE, BUFFERS)` without and with the index (none served only by a PK or UNIQUE).
- [ ] The app does not connect as `postgres` or `root`.
- [ ] `git log -p | grep -i password` shows no real password.
- [ ] Every document exists and is complete, including the declaration in `ai-usage.md`.
- [ ] Each member has at least one non-trivial commit in each of the 4 areas.
- [ ] Squash merging turned off.
- [ ] SemVer tag pushed before session 19 starts.
