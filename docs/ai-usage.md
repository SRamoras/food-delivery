# AI usage

## Dev container build failure

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** diagnosing why the dev container would not open; `.devcontainer/Dockerfile`, `.devcontainer/compose.devcontainer.yml`
- **Outcome:** kept. The base image's Yarn apt repo has no valid GPG key, so `apt-get update` failed while installing the `docker-outside-of-docker` feature. The repo is now removed before the feature is installed.
- **Verification:** ran `devcontainer up` with the dev container CLI on a temporary copy of the repo (databases healthy, `uv sync` finished, Python imports and the Docker CLI worked inside the container), then `docker compose config` and a build of the `workspace` service in the repo itself.
- **Mistakes caught:** none in the fix. The first test run failed because it used the system's Node v12, so it was repeated with the Node from the VS Code Server.

## Daily stock model

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** drafting the `DailyStock` model and explaining its primary key, `CHECK` and foreign key; `app/models/orders.py`
- **Outcome:** kept. The code was typed by hand from the AI's draft. The `int` type of `item_id` is provisional until the type of `menu_items.id` is confirmed, and the migration that creates the table is a separate step.
- **Verification:** `ruff check` and `ruff format --check` passed. The model was imported and the generated `CREATE TABLE` was inspected, using a temporary `menu_items` table in memory only, to confirm the primary key, the `CHECK`, the foreign key and the constraint names. This does not yet prove that PostgreSQL refuses a negative value; that is tested with the migration.
- **Mistakes caught:** the AI's first draft used `BigInteger` for `item_id`, without knowing the real type of `menu_items.id`, had no `ON DELETE` rule and used a constraint name different from the project guide. It was corrected before the model was written.

## Daily stock migration

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and testing the migration that creates `daily_stock`; `postgres/migrations/versions/20261106_08211037a94a_add_daily_stock_table.py`
- **Outcome:** kept, with `down_revision` provisional. It must point at the catalogue migration once `menu_items` exists, and it cannot reach `dev` before that.
- **Verification:** applied with `alembic upgrade head` against a temporary `menu_items` table, which was removed afterwards. PostgreSQL refused a negative `remaining`, a second row for the same item and day, and an unknown item. Deleting the item removed its stock rows, and `fd_app` received its grants without a `GRANT` in the migration. `upgrade` fails without `menu_items`, and `downgrade` works. To be repeated with the real table.
- **Mistakes caught:** one line written by the AI failed `ruff format --check`, and it was formatted before the commit.

## Order models

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** drafting the `Order`, `OrderLine` and `OrderStatusHistory` models and explaining their constraints, indexes and `ON DELETE` rules; `app/models/orders.py`
- **Outcome:** kept. The code was typed by hand from the AI's draft. Two of RodrigoDias123's decisions were applied: `cancelled_by` is stored in `orders` as well as in the history, and cancel reasons are a fixed list with a `CHECK`. Column sizes and id types are provisional until the catalogue tables exist.
- **Verification:** `ruff check` and `ruff format --check` passed. The models were imported and their SQL was generated with the missing tables simulated in memory, to check the columns, `CHECK` constraints, foreign keys and indexes. This does not yet prove that PostgreSQL enforces them; that is tested with the migration.
- **Mistakes caught:** none in the draft. `ruff format --check` found a missing blank line after the code was typed, and it was fixed before the commit.

## Payment model

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** drafting the `Payment` model and explaining its `CHECK` constraints and partial unique indexes; `app/models/payments.py`
- **Outcome:** kept. The code was typed by hand from the AI's draft. Refunds are new rows, and a refund by card or MB WAY needs its own reference because `provider_ref` is unique; the refund itself is written in a later step.
- **Verification:** `ruff check` and `ruff format --check` passed. The model was imported and its SQL was generated with `orders` simulated in memory, to check the columns, `CHECK` constraints, foreign key and indexes. This does not yet prove that PostgreSQL enforces them; that is tested with the migration.
- **Mistakes caught:** none.

## Order tables migration

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and testing the migration that creates `orders`, `order_lines`, `order_status_history` and `payments`, with the `REVOKE` that makes the history append-only; `postgres/migrations/versions/20261106_243dbb92484a_add_order_tables.py`
- **Outcome:** kept, but provisional. Id types and `delivery_*` column sizes must be checked against the catalogue tables, and the migration cannot reach `dev` before those tables exist. The project guide suggested a `GRANT` in `downgrade()`; it was left out because dropping the table already removes its grants.
- **Verification:** applied with `alembic upgrade head` against temporary catalogue tables, which were removed afterwards. Valid rows were accepted as `fd_app`. PostgreSQL refused rows that broke the `CHECK` constraints, the unique indexes and the `RESTRICT` foreign keys. On a real `fd_app` connection, `UPDATE`, `DELETE` and `TRUNCATE` on the history gave `permission denied`. An Alembic comparison found no differences between the models and the database, although it does not compare `CHECK` constraints, and `downgrade` worked. To be repeated with the real tables.
- **Mistakes caught:** none.

## Catalogue models and migrations

- **Who:** jcleberfernandes
- **Tool:** Claude Code
- **For what:** catalogue models (`app/models/geo.py`, `customers.py`, `restaurants.py`, `menu.py`), the two catalogue migrations (`a0f0fea02357`, `cc5a58ef4086`), and pointing `08211037a94a` at `cc5a58ef4086` so that it runs after the tables it depends on. The commits were also made by the tool, at the member's request.
- **Outcome:** kept. The `EXCLUDE` on opening hours was added by hand to the generated migration. `ON DELETE` choices and the `down_revision` change are to be confirmed by the group.
- **Verification:** ran upgrade and downgrade; psql tests refused a second default address, an 8-digit NIF and overlapping hours, and accepted adjacent periods and a full day; `setup.sh` from an empty database applied all 5 migrations in order; `alembic check` reported no differences; ruff passed.
- **Mistakes caught:** the first run from an empty database failed with two Alembic heads, fixed by the `down_revision` change. `alembic check` then reported the order tables as removed because `orders` and `payments` were not imported in `app/models/__init__.py`; the import was added.

## Order status machine

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and explaining the shared status machine used by F2, F3 and F5 (allowed transitions, who may make each one, `SELECT ... FOR UPDATE` on the order, history row in the same transaction); `app/services/order_status.py`, `tests/test_order_status.py`
- **Outcome:** kept. The AI wrote the files from the project guide. RodrigoDias123 asked for comments explaining each function, and they were added. A reject may give a reason but does not need one; SRamoras has to be told, because F3 reject uses this function.
- **Verification:** `ruff check` and `ruff format --check` passed. 8 `pytest` cases without a database: 4 allowed and 4 refused transitions (backwards, too late to cancel, final status, wrong actor). The row lock is not tested yet; that needs two real requests at the same time (steps 6 and 8).
- **Mistakes caught:** the AI first wrote a longer test file without asking, and proposed a commit message different from the guide's. Both were changed back to the guide's version. `ruff check` found unsorted imports in the AI's test file, and they were fixed before the commit.

## Place-order schemas and option pricing

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and explaining the Pydantic request and response models for orders, and the unit price of a line from the `menu_items.options` jsonb (item price plus extras, with a snapshot of the chosen options); `app/schemas/orders.py`, `app/services/pricing.py`, `tests/test_pricing.py`
- **Outcome:** kept, with two decisions by RodrigoDias123. An option group without `max` allows one choice, so groups that allow more (such as removals) need an explicit `max` in jcleberfernandes's catalogue data. The cancel reason is a `Literal` with the 6 fixed reasons, not free text.
- **Verification:** `ruff check` and `ruff format --check` passed. 8 `pytest` cases without a database: the price with extras is exact (12.60, no float error) and so is the snapshot; an unknown group or choice, a chosen allergen, two choices in a group without `max` and a missing required group give 409; the reason list matches `CANCEL_REASONS`; a reason outside the list fails validation (422).
- **Mistakes caught:** the guide's draft had the cancel reason as free text. Because of the `CHECK` on `orders.cancel_reason`, a reason outside the list would pass Pydantic and then fail in PostgreSQL as a 500, which `CLAUDE.md` does not allow. The AI pointed this out before writing the code, and the `Literal` that the guide offers for a fixed list was used instead.

## Daily stock decrement

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and explaining the lazy creation of today's stock row (`INSERT ... ON CONFLICT DO NOTHING` from `menu_items.daily_stock`) and the conditional decrement that enforces rule 2 (`UPDATE ... WHERE remaining >= :qty RETURNING remaining`, 0 rows → 409); `app/services/stock.py`
- **Outcome:** kept. The AI wrote the file from the project guide. RodrigoDias123 chose plain SQL in `text()` over the ORM, so the rule 2 statement reads the same in the code, in `CLAUDE.md` and in `docs/concurrency.md`; every value is a bound parameter. The column name `menu_items.daily_stock` was checked in jcleberfernandes's model. Locking items in ascending `item_id` order (to avoid deadlocks) is left to the caller, `place_order`.
- **Verification:** `ruff check` and `ruff format --check` passed. A scratch script outside the repo, connected as `fd_app` to the real schema: the first call created today's row only for the item with a configured stock, and a second call did not reset it. Then 60 threads, each in its own transaction and released together by a barrier, took 1 portion of an item with 30: 30 succeeded, 30 got "sold out", 0 other errors, the stock ended at 0, and each value from 0 to 29 was returned exactly once. The test data was deleted afterwards.
- **Mistakes caught:** none.

## Place order service (F2)

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and explaining `place_order`, the single transaction of F2 (declined payment, address ownership, restaurant open and within its Lisbon hours, delivered zone, available items from one restaurant, option prices and minimum, daily stock in ascending `item_id` order, then the order with its address snapshot, lines, approved payment and first history row); `app/services/orders.py`. Also merging `origin/cleber` into `Rodrigo`, because without jcleberfernandes's models SQLAlchemy could not resolve the foreign keys of `orders` (`NoReferencedTableError` on flush).
- **Outcome:** kept. The AI wrote the file from the project guide, adapted to jcleberfernandes's real tables. The merge had one conflict, in `docs/ai-usage.md` (both sides added entries); both were kept. Only the stock is protected against concurrency; the other checks are plain reads, which is accepted and will be explained in `docs/concurrency.md`.
- **Verification:** `ruff check`, `ruff format --check` and `pytest` passed. A scratch script outside the repo ran every case against the real schema as `fd_app`, each in a savepoint, all rolled back at the end: 11 refusals with the right error (declined, another customer's address → 404, restaurant closed, open every weekday except today, zone not delivered, two restaurants, unavailable item, unknown item, below minimum, required option missing, 2 + 2 portions of an item with 3 left), none of them left an order or a stock row; a card order gave subtotal 24.20, fee 2.50, tip 1.00, total 27.70, a `sim_` reference, history `None → placed` by the customer and stock 3 → 1; a cash order had no reference and an item without a limit took no stock.
- **Mistakes caught:** the guide read `menu_items.restaurant_id`, which does not exist (items belong to a category, so the query joins `menu_categories`), and used `isoweekday()` (Monday = 1) while `opening_periods.weekday` uses 0 = Monday, which would have checked the next day's hours. Both were fixed before writing the code. The test then found that `hours @> :m` failed with `operator does not exist: int4range @> smallint`, because psycopg sends small integers as `smallint`; without `CAST(:m AS integer)` every order would have been a 500.

## Place order endpoint (F2)

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and explaining `POST /customers/{customer_id}/orders`, a thin `def` route that opens one transaction, calls `place_order` and returns 201 with `OrderOut`; `app/routers/orders.py`, and two lines in SRamoras's `app/main.py` to include the router where he left the comment for it
- **Outcome:** kept, with two differences from the project guide, chosen by RodrigoDias123: no `?mode=naive` yet (it arrives with `take_stock_naive` in step 4), and no `side_effects.py` yet (the Redis stock copy is step 5 and the tracking function is jcleberfernandes's; importing functions that do not exist yet would log an error on every order). SRamoras has to be told about the change to `main.py`.
- **Verification:** `ruff check`, `ruff format --check` and `pytest` passed. The API was run locally with `uvicorn` against test data created as `postgres` and deleted afterwards. 8 `curl` requests: `simulate: declined` → 409 with the row counts of `orders`, `order_lines`, `payments`, `order_status_history` and `daily_stock` the same before and after; a valid card order → 201 (subtotal 19.00, fee 2.50, tip 1.00, total 22.50) with one order, line, `sim_` payment and `None → placed` history row, and stock 5 → 3; another customer's address → 404; below the minimum → 409; 4 portions with 3 left → 409 `sold out`; quantity 0, an unknown payment method and no lines → 422. No 500 in the server log. `/docs` lists the route with its docstring as the description.
- **Mistakes caught:** none in the code. The first command used to stop the test server matched its own command line and ended the shell before `git status` ran; it was run again.

## Naive stock path for the race demo

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and explaining `take_stock_naive` (read with a plain `SELECT`, check in Python, write the absolute value with `SET remaining = :new`, no lock, on purpose), the `naive` switch in `place_order`, and `?mode=real|naive` on the place-order route, which answers 404 when `ENABLE_NAIVE_MODE` is off; `app/services/stock.py`, `app/services/orders.py`, `app/routers/orders.py`. Also one-line docstrings for every class and function in RodrigoDias123's files that had none (`PlacedOrder`, the order schemas, the test functions), at his request; `app/schemas/orders.py`, `tests/test_order_status.py`, `tests/test_pricing.py`.
- **Outcome:** kept. The naive path writes the absolute value, as the project guide recommends: the result is a silent lost update (more orders than portions, no error), which shows the race better than a `CHECK` failure (500); both are to be explained in `docs/concurrency.md`. No artificial delay (`pg_sleep`) was needed, because the race showed up without it. `CLAUDE.md` asks for no docstrings on trivial Pydantic schemas; they were added anyway because RodrigoDias123 asked, kept to one line each.
- **Verification:** `ruff check`, `ruff format --check` and `pytest` passed, and a script confirmed that no class or function in these files is left without a docstring. A scratch script outside the repo ran 60 threads, each in its own transaction, against an item with 30 portions, as `fd_app`: naive mode 3 times → 60 sold, 0 sold out, 0 errors, stock ending at 27, 27 and 28; real mode once → 30 sold, 30 sold out, 0 errors, stock 0. Over HTTP with `uvicorn`: switch on, `?mode=naive` and `?mode=real` → 201, `?mode=fast` → 422; switch off, `?mode=naive` → 404 `naive mode is disabled`, no mode → 201. No 500 in the server log, and the test data was deleted afterwards.
- **Mistakes caught:** none.

## Docker Compose, image and uv project

- **Who:** SRamoras
- **Tool:** Claude Code
- **For what:** the Compose file with `postgres`, `mongo`, `redis`, `api` and `dbgate` (profile `tools`), the API image and the uv project; `compose.yml`, `Dockerfile`, `.dockerignore`, `.env.example`, `pyproject.toml`, `uv.lock`
- **Outcome:** kept, with one fix. The project was made installable so that the scripts in `postgres/`, `mongodb/` and `redis/` can import `app`.
- **Verification:** `docker compose up -d` from a clean clone, `ruff check` and `ruff format --check`.
- **Mistakes caught:** the top-level `redis/` folder made ruff sort `import redis` as our own code instead of the redis-py library. The ruff cache hid it on the host, and it was caught with `--no-cache`. Fixed with `known-third-party = ["redis"]` in `pyproject.toml`.

## App base and database setup

- **Who:** SRamoras
- **Tool:** Claude Code
- **For what:** settings, connections, error handlers and the health check (`app/config.py`, `app/db/*.py`, `app/errors.py`, `app/main.py`); the setup script that creates the roles, the database and the extensions (`scripts/setup.sh`); the Alembic setup and the default privileges migration (`postgres/alembic.ini`, `postgres/migrations/`); the MongoDB app user and the `ensure_collection` helper (`mongodb/setup.py`)
- **Outcome:** kept, with one fix to the roles in `setup.sh`.
- **Verification:** `./scripts/setup.sh` on an empty database after `docker compose up -d`; checked which databases each role can connect to; started the API and called the health check.
- **Mistakes caught:** the first `setup.sh` only restricted `food_delivery`, so `fd_app` and `fd_readonly` could still connect to the built-in `postgres` and `template1` databases, which every role can by default. Fixed with `REVOKE CONNECT ON DATABASE postgres, template1 FROM PUBLIC`.

## Seed script, Redis skeletons and dev container

- **Who:** SRamoras
- **Tool:** Claude Code
- **For what:** the seed script and the `.env` loading it shares with `setup.sh` (`scripts/seed.sh`); the skeletons of `redis/rebuild.py` and `redis/verify.py`; placeholder folders for the seeds and the concurrency tests; the dev container (`.devcontainer/`)
- **Outcome:** seed script and Redis skeletons kept. The dev container was changed twice: the first version, which started the databases through Compose with an extra `workspace` service, was replaced by a plain Python image, and then by the `docker-in-docker` feature.
- **Verification:** opened the dev container and ran `ruff` inside it.
- **Mistakes caught:** the AI's dev container added a separate Compose file and service that the project did not need and did not give a working Docker inside the container; the Compose file was removed and Docker was added.

## README and project guidelines

- **Who:** SRamoras
- **Tool:** Claude Code
- **For what:** the README sections on how to run, the stack and the project overview (`README.md`); the AI guidelines and the group plan (`CLAUDE.md`, `planning/`)
- **Outcome:** kept. The planning files are the group's internal plan, not graded documentation.
- **Verification:** followed the README commands from a clean clone (`cp .env.example .env`, `docker compose up -d`, `./scripts/setup.sh`).
- **Mistakes caught:** none.

## Couriers table

- **Who:** SRamoras
- **Tool:** Claude Code
- **For what:** the `Courier` model and the migration that creates `couriers`; `app/models/couriers.py`, `app/models/__init__.py`, `postgres/migrations/versions/20261109_df4595780c71_add_couriers_table.py`
- **Outcome:** kept. The autogenerated migration was reviewed; the long `CHECK` string was split for ruff and a note explains why there is no `GRANT`.
- **Verification:** `alembic upgrade`, `downgrade -1` and `upgrade` again; `alembic check` reported no differences; as `fd_app`, PostgreSQL refused a bicycle with a plate, a car without one, a repeated plate, email and phone, an unknown vehicle type and status, and changing a car to a bicycle while keeping its plate; two bicycles without a plate were accepted; ruff passed.
- **Mistakes caught:** none.

## F7: courier online, position and offline

- **Who:** SRamoras
- **Tool:** Claude Code
- **For what:** the position Lua script and the F7 endpoints; `redis/scripts/courier_position.lua`, `app/db/redis.py`, `app/services/couriers.py`, `app/schemas/couriers.py`, `app/routers/couriers.py`, `app/main.py`
- **Outcome:** kept. Two choices beyond the plan: `/position` only works while the online key exists (the check is inside the Lua script, so it is atomic with the write), which means PostgreSQL is read only by `/online` and the blocked check runs there; and `/offline` is idempotent. `order_id` in the trail is left for when `deliveries` exists (C-4).
- **Verification:** ruff passed; with the API running locally: `/online` → 200 and the courier showed in `GEOSEARCH ... BYRADIUS 3 km` with the online key at `TTL 30`; `/position` → 200 and a second document in `courier_positions`; blocked courier → 409, unknown courier → 404, longitude 200 → 422, `/position` before `/online` or after `/offline` → 409; after 31 s without positions the online key was gone and `/position` gave 409. Test rows, keys and documents were removed.
- **Mistakes caught:** none.

## courier_positions collection

- **Who:** SRamoras
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** the `courier_positions` collection in `mongodb/setup.py`: `$jsonSchema` validator, 7-day TTL index and `{courier_id: 1, recorded_at: -1}` index
- **Outcome:** kept the validator and the two indexes. No 2dsphere index, because no query uses it yet and every index must serve a query.
- **Verification:** ran `setup.py` twice (idempotent); as `fd_app`, inserted valid and invalid documents (missing `courier_id`, string date, latitude out of range, unknown field), and the invalid ones were refused with code 121; `list_indexes()` shows `expireAfterSeconds: 604800`.
- **Mistakes caught:** none in the output. Noted that integer coordinates would be refused by the `double` type, so the seed must write floats.

## Delivery offers and deliveries tables

- **Who:** SRamoras
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** the `DeliveryOffer` and `Delivery` models and the migration that creates `delivery_offers` and `deliveries` (step C-4); `app/models/offers.py`, `app/models/__init__.py`, `postgres/migrations/versions/20261110_1fd8078fc277_add_delivery_offers_and_deliveries.py`
- **Outcome:** kept. The autogenerated migration was reviewed: added a note on why there is no `GRANT` and split a long `CHECK` string. Kept two extras beyond the plan: a partial unique index allowing one accepted offer per order (a second guard for rule 1) and `CHECK`s that delivery times only move forward. All foreign keys are `RESTRICT`, because offers and deliveries feed the reports.
- **Verification:** `alembic upgrade`, `downgrade -1` and `upgrade` again; `alembic check` reported no differences; as `fd_app`, inside a transaction rolled back at the end, PostgreSQL refused a repeated offer, an unknown outcome, two accepted offers for one order, a second delivery for one order, a negative distance, delivered without picked up, picked up before accepted, and deleting an order with a delivery; a full accepted → picked up → delivered row was accepted; `EXPLAIN` showed the courier's active deliveries query using `ix_deliveries_courier_active`; ruff passed on the new files.
- **Mistakes caught:** none in the output. Noted that a delivery whose order is cancelled before pick-up keeps `delivered_at` NULL, so the active deliveries count in F3/F4 must also exclude cancelled orders.

## Daily stock copy in Redis

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and explaining the derived Redis copy of the daily stock: `stock_key`, `stock_expire_at` and `write_stock_copies` (`SET fd:stock:{item_id}:{yyyy-mm-dd} <remaining> EXAT <next Lisbon midnight + 1 h>`, with the value PostgreSQL returned) in `app/services/stock.py`; `after_order_placed` in the new `app/services/side_effects.py`, called by the place-order route only after the commit and wrapped in `try/except` so a Redis failure never turns a committed order into a 500; and the bodies of `rebuild_stock` and `verify_stock` in SRamoras's `redis/rebuild.py` and `redis/verify.py` (his functions and jcleberfernandes's were not touched).
- **Outcome:** kept, from the project guide. `side_effects.py` does not import the tracking function yet, because it does not exist; it is added when jcleberfernandes's function lands. Known limit, to be written in `docs/architecture.md` and `docs/redis.md`: two orders finishing almost together can write Redis out of order and leave the older value until the next write; `verify.py` finds it, and rule 2 is still enforced by PostgreSQL. The key table was given to SRamoras for `docs/redis.md`.
- **Verification:** `ruff check`, `ruff format --check` and `pytest` passed. With `uvicorn`, PostgreSQL and Redis running and test data deleted afterwards: a real and a naive order → 201, `MONITOR` showed one `SET ... EXAT 1794272400` per item, Redis matched PostgreSQL, and `EXPIRETIME` was 2026-11-10 01:00 Lisbon time. `verify.py` → exit 0; after setting a wrong value and an extra key by hand → 2 differences, exit 1; `rebuild.py` → exit 0. After deleting every `fd:stock:*` key (instead of `FLUSHALL`, which would also remove other people's keys) → 2 missing, exit 1; `rebuild.py` restored them with their TTL → exit 0. With the API given a wrong Redis password, an order still returned 201, the log showed `fd:stock update failed ... AuthenticationError`, `verify.py` found the stale key (exit 1) and `rebuild.py` fixed it (exit 0). No 500 in the server logs.
- **Mistakes caught:** the first verification command printed the exit code of `grep` instead of `verify.py`'s, because of a pipe; it was rerun with the real exit code before any result was reported.

## Kitchen steps and cancel (F5)

- **Who:** RodrigoDias123
- **Tool:** Claude Code
- **For what:** writing and explaining F5 on the restaurant and cancel side: `release_stock` (portions go back to the stock row of the order's Lisbon day, rows locked in ascending `item_id` order) in `app/services/stock.py`; `refund_if_paid_online` (a new `refunded` row with its own `rf_` reference, card and MB WAY only) in the new `app/services/payments.py`; `StatusChange`, `release_and_refund` (also for SRamoras's F3 reject), `_check_owner` (404 on another customer's or restaurant's order), `kitchen_step` and `cancel_order` in `app/services/orders.py`; `after_status_change` (Redis copy of today's stock only, after the commit) in `app/services/side_effects.py`; and the routes `POST /restaurants/{id}/orders/{order_id}/preparing`, `.../ready`, `.../cancel`, `POST /customers/{id}/orders/{order_id}/cancel` and `POST /backoffice/orders/{order_id}/cancel` in `app/routers/orders.py`.
- **Outcome:** kept, from the project guide, except step 6.4: ending the courier's delivery and withdrawing pending offers on cancel wait for SRamoras's `deliveries` table (proposed marker `cancelled_at timestamptz NULL`, active = `delivered_at IS NULL AND cancelled_at IS NULL`) and his `withdraw_offers` function. The guide's placeholder that does nothing was not added, so no function pretends to end a delivery. Lock order in every flow: the order first, then its stock rows.
- **Verification:** `ruff check`, `ruff format --check` and `pytest` passed. With `uvicorn`, PostgreSQL and Redis running and test data deleted afterwards: a customer cancel of a card order → 200, reason and actor stored, stock 18 → 20 in PostgreSQL and Redis, `approved` + `refunded` rows of 21.50, history `placed → cancelled` by the customer; a back office cancel of a cash order → 200 with no refund; `preparing` while `placed` → 409, by another restaurant → 404, `preparing` → `ready` → 200, `ready → preparing` → 409, cancel after `picked_up` or twice → 409; another customer or restaurant → 404; a free-text reason or no body → 422; 10 simultaneous cancels of one order → 1 × 200 and 9 × 409, portions back once, one refund, one history row; an order from yesterday cancelled today gave its portions to yesterday's row and wrote no Redis key; `redis/verify.py` → exit 0; no 500 in the server log. The `accepted` status for the kitchen test was set directly in the database, because accepting is SRamoras's F3, so that history has no `placed → accepted` row.
- **Mistakes caught:** none in the code. A one-line command to list the routes failed (`_IncludedRouter` has no `path`); the routes were checked through the HTTP tests instead.

## Courier steps and tracking updates (F5)

- **Who:** RodrigoDias123
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** F5 on the courier side and the tracking calls of every status change: `courier_step` (order locked first, the delivery must be this courier's, `picked_up_at`/`delivered_at` set with `now()`) and `distance_km` (straight-line haversine from the restaurant to the address snapshot) in `app/services/orders.py`; cancel now withdraws the order's pending offers; `after_order_placed` and `after_status_change` call jcleberfernandes's `update_tracking` after the commit, failures only logged (`app/services/side_effects.py`); the routes `POST /couriers/{id}/deliveries/{order_id}/picked-up` and `.../delivered` in `app/routers/orders.py`; `tests/test_distance.py`.
- **Outcome:** kept. Two parts are still open: ending a delivery a courier already accepted when the order is cancelled (step 6.4) waits for the marker to be agreed with SRamoras in `deliveries`, and the ranking call on `delivered` waits for jcleberfernandes's function.
- **Verification:** `ruff check`, `ruff format --check` and `pytest` passed. With PostgreSQL and Redis running and the test data deleted afterwards: one order went `placed → … → delivered` through the API (the accept and the delivery row were written directly, standing in for F3/F4); pickup while `accepted` → 409, pickup by another courier → 404, pickup and delivered twice → 409, cancel after pickup → 409; the delivery row had times in order and a distance; six history rows; the tracking hash showed `delivered` with the courier; a cancel withdrew a pending offer, gave the stock back and added the refund; `redis/verify.py` exited 0.
- **Mistakes caught:** none in the code. ruff flagged `Decimal("270")` in the new test (FURB157), fixed to `Decimal(270)`.

## Merge of main and pull request description

- **Who:** RodrigoDias123
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** bringing `main` (SRamoras's PR #12 and jcleberfernandes's PR #13) into the `Rodrigo` branch and resolving the conflict in `docs/ai-usage.md`; writing the title and description of the pull request for steps 5 to 7.
- **Outcome:** kept. The conflict was two sets of entries added at the end of this file; both were kept, the other members' entries first. The first merge was aborted and redone so that it also included PR #13, leaving a single merge commit. The PR description lists what is still open (cancel after a courier accepted, ranking call) instead of hiding it.
- **Verification:** no conflict markers left; `alembic heads` showed a single head; `ruff check`, `ruff format --check` and `pytest` passed and `app.main` imported after the merge; `git merge-tree` against `origin/main` reported no conflicts before opening the PR.
- **Mistakes caught:** the merge was first done without PR #13, which had been merged into `main` in the meantime; it was aborted and redone before committing.

## Last portions concurrency scenario

- **Who:** RodrigoDias123
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** the "last portions" scenario for rule 2 in `tests/concurrency/last_portions.py`: `fixture` (deletes the previous run's rows, then creates one restaurant open 00:00–24:00 every day, one item with stock 30 and 60 customers in a delivered zone, straight in PostgreSQL), `attack` (60 orders of 1 portion, `simulate=approved`, fired together with `httpx.AsyncClient` and `asyncio.gather`; returns the status codes) and `check` (stock = 0 and exactly 30 orders). The shared runner `tests/concurrency/run.py` is jcleberfernandes's; as the plan says, it calls each scenario's fixture and attack and counts the codes.
- **Outcome:** changed twice to follow the plan. The first version created fresh rows on every run and checked portions sold + portions left = 30; now `fixture` deletes the previous run's rows (found by a fixed NIF, city name and emails) and `check` asks for stock = 0 and 30 orders. The delete runs as the owner (`MIGRATION_DATABASE_URL`), because `fd_app` has no `DELETE` on the append-only status history and that grant is not loosened for a test; the data is still created as `fd_app`, and the derived Redis keys of the deleted rows are removed too. The second change moved the attack from the temporary runner into the scenario, because the plan gives the attack to the scenario's owner.
- **Verification:** with the API running locally and a temporary runner that calls `fixture`, `attack` and `check`: real mode gave 30 succeeded, 30 refused (409 "sold out"), 0 failed, stock 0 and 30 orders, three times in a row; naive mode gave 60 orders with 27–28 portions still in stock (lost update), three times in a row. After the runs the database held only the last run's data, and `redis/verify.py` exited 0. `ruff check`, `ruff format --check` and `pytest` passed.
- **Mistakes caught:** the attack was first left in the temporary runner instead of the scenario. While writing this entry, an edit replaced the "Mistakes caught" line of every older entry in this file; it was caught in the diff and the file was restored from the last commit before adding this entry.

## Orders seed

- **Who:** RodrigoDias123
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** `postgres/seed/orders.py`: about 418k orders over the last 12 months, 1.1M lines, 443k payments, 2.4M status history rows and today's `daily_stock` rows, loaded with psycopg `COPY` in batches of 50k orders, in one transaction, as `fd_app`. Orders fall inside each restaurant's opening hours (Lisbon time) with lunch and dinner peaks, only to delivered zones, never below the minimum; ~5% cancelled (actor and reason), ~2% rejected, refunds for online payments; per-restaurant and per-zone speeds so the report pipelines have something to show.
- **Outcome:** kept, after fixes. Order ids come from `nextval` on `orders_id_seq`, because `fd_app` may use the sequence but not `setval` it. A second run skips instead of adding duplicates (`fd_app` cannot delete the history). Courier history rows have `actor_id` NULL, because couriers are seeded after orders (A's seed).
- **Verification:** tested on a temporary catalogue with the brief's volumes (C's catalogue seed does not exist yet), not committed. The run took about 31 s. SQL checks all returned 0: history out of time order, first row ≠ `created_at`, last row ≠ order status, cancel actor ≠ history actor, today's stock ≠ stock − portions sold, orders outside opening hours, zone not delivered or wrong fee, subtotal ≠ sum of lines, below minimum, missing or wrong refunds, payment ≠ total. Top 20% of restaurants and of customers have about 65% of the orders; the busiest customer has 261 orders a year, the median 4. `seed.sh` ran it and `redis/verify.py` exited 0 after the rebuild. `ruff check`, `ruff format --check` and `pytest` passed.
- **Mistakes caught:** `setval` was refused for `fd_app` (replaced by `nextval`). Adding minutes to a Lisbon time put one order's `delivered` before `placed` on the night the clocks changed (the timeline is now in UTC). Stock was taken before checking the minimum order, so dropped orders used up portions (now taken only once the order is kept). An uncapped Zipf per customer gave one customer 7,894 orders a year (now a capped Pareto weight).

## Pipeline 4: cancellations

- **Who:** RodrigoDias123
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** `mongodb/pipelines/cancellations.py` (pipeline 4: per restaurant, last 90 days, orders, cancellations, cancel rate and the split by who cancelled and reason; same `COLLECTION` + `build()` shape as jcleberfernandes's pipelines) and `REPORT_ORDERS_CANCEL_SCHEMA` in `mongodb/setup.py` (the `report_orders` fields pipeline 4 reads, as a sub-schema for C's validator to include with `allOf`; enums equal to the PostgreSQL CHECKs; `oneOf` so a cancelled order must have `cancelled_by`, `cancel_reason` and `cancelled_at`, and any other order has no `cancelled_by`).
- **Outcome:** kept. The pipeline reads every order of the window, not only cancelled ones, so it can give the rate. The `report_orders` validator, the export and the F8 route are jcleberfernandes's and not merged yet, so the sub-schema is not applied by `setup.py` yet and the pipeline is not in `REPORTS` yet.
- **Verification:** on a temporary collection with the sub-schema as validator (dropped afterwards), filled with 137k documents built from the seeded PostgreSQL orders of the last 100 days: the four invalid documents tried (cancelled without actor, delivered with `cancelled_by`, unknown reason, date as string) were refused and a rejected order with a reason was accepted; the pipeline returned 1,065 restaurants and its total of cancellations (6,275) matched a `count(*)` in PostgreSQL for the same 90 days. `ruff check`, `ruff format --check` and `pytest` passed. Checked on GitHub that no other branch (`cleber`, `SRamoras`, `main`) already had pipeline 4, and that `mongodb/setup.py` on `cleber` is still the same as on `main`, so the new sub-schema does not conflict with it.
- **Mistakes caught:** none.

## Kitchen capacity (rule 4)

- **Who:** RodrigoDias123
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** `ensure_kitchen_room` in the new `app/services/kitchen.py` (lock the restaurant row with `FOR UPDATE`, count its orders in `accepted`/`preparing`/`ready`, 409 when the count reached `kitchen_capacity`), for SRamoras to call inside F3 accept; the kitchen capacity section of the new `docs/postgres.md` (where and how the rule is enforced, why a lock, why in the app).
- **Outcome:** kept. F3 accept is SRamoras's and does not exist yet, so the function is not called by any endpoint yet.
- **Verification:** a script against the local database (rows created as the owner and deleted afterwards) did what F3 accept will do: lock the order, call the function, set `accepted`, in one transaction. Capacity 2 with 2 orders in preparation → the third accept got 409; after a cancel it got through. 10 simultaneous accepts with one slot left: with the function, 1 accepted and 9 refused, three times; with the same count without `FOR UPDATE`, all 10 accepted (11 active for capacity 2), three times. `ruff check`, `ruff format --check` and `pytest` passed.
- **Mistakes caught:** none.

## Orders seed: orders still in progress

- **Who:** RodrigoDias123
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** `postgres/seed/orders.py`: today's orders now go up to 5 minutes ago. Each order keeps only the steps of its timeline that already happened, so the most recent ones stay `placed`, `accepted`, `preparing`, `ready` or `picked_up`. A future cancel or reject is not written yet. The seed respects the kitchen capacity: an order that would go over it stays `placed`. Orders still in progress keep their stock. `postgres/sql/explain_orders.sql`: frequent queries 2 and 3, without and with their index.
- **Outcome:** kept. Found while writing the `EXPLAIN` for query 3: every seeded order was finished, so the kitchen screen query returned 0 rows and showed nothing.
- **Verification:** reseeded on the temporary catalogue: 533 orders in progress (at about 19:40 Lisbon time), 0 restaurants over capacity, 0 history rows in the future, 0 cancel fields on orders not yet cancelled; the earlier checks (history order, last status, today's stock, refunds, opening hours, subtotals) still all 0. `ruff check`, `ruff format --check` and `pytest` passed.
- **Mistakes caught:** none.

## PostgreSQL, concurrency and runbook documentation

- **Who:** RodrigoDias123
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:**
  - `docs/postgres.md`: tables, both lists of "Where the rules are enforced" with the constraint or code for each, denormalisations, indexes with their query, `EXPLAIN (ANALYZE, BUFFERS)` of queries 2 and 3 without and with the index, indexed and not-indexed FKs;
  - `docs/concurrency.md`: isolation level, rule 2 with the naive version and the 6 last-portions outputs, the order lock for status changes, rule 4 with its test;
  - `docs/runbook.md`: the PostgreSQL section.
  
  Sections of other members are left as marked to-dos.
- **Outcome:** kept. The constraint, index, FK and grant lists were taken from the live database (`pg_constraint`, `pg_indexes`, `information_schema.role_table_grants`), not written from memory. The last-portions outputs come from the temporary runner and must be taken again with the shared `run.py`.
- **Verification:**
  - the `EXPLAIN` outputs were run on the seeded data (418k orders);
  - the backup and restore A commands were run as written: a dump to the host, then a restore into a scratch database, which matched the original in row counts, `alembic_version`, 103 constraints and the history grant, and was then dropped;
  - restore B (point in time) is not drilled, and the runbook says so.
- **Mistakes caught:**
  - the first restore failed on `COMMENT ON EXTENSION btree_gist`, which only the superuser can set; `--no-comments` was added to the documented command;
  - restore B first moved the data directory itself, which is the volume's mount point and cannot be moved; it now moves the directory's contents.

## Commits for the seed update and the documentation

- **Who:** RodrigoDias123
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** at RodrigoDias123's explicit request, Claude Code ran `git add` and `git commit` for the seed update (`postgres/seed/orders.py`, `postgres/sql/explain_orders.sql`), the documentation (`docs/postgres.md`, `docs/concurrency.md`, `docs/runbook.md`) and these ai-usage entries, as three separate commits. Before that it checked what is still open in RodrigoDias123's slice.
- **Outcome:** kept. The commits use RodrigoDias123's own git identity and have no `Co-authored-by` line, so they count for this member as the course rules require. Local files that are not part of the project (`PROGRESS-B.md`, `Claude./`) were left out.
- **Verification:** `git config user.email` checked before committing; `git status` after each commit showed only the intended files staged; `ruff check`, `ruff format --check` and `pytest` passed before committing.
- **Mistakes caught:** none.
## F3: restaurant accepts, rejects and reoffers

- **Who:** SRamoras
- **Tool:** Claude Code (Claude Opus 5.5)
- **For what:** accept (with offers to nearby couriers), reject and reoffer, and the kitchen capacity check that F3 accept calls; `app/services/offers.py`, `app/routers/offers.py`, `app/schemas/offers.py`, `check_kitchen_capacity` in `app/services/orders.py` (RodrigoDias123's file, written with his agreement), `app/main.py`
- **Outcome:** kept. Offers still inside their 45 s stay `pending` on reoffer; only older ones become `expired`. Choosing couriers with room is only a first pass; F4 re-checks with the courier row locked.
- **Verification:** an end-to-end script against the running API, 3 runs: 4 simultaneous accepts with kitchen capacity 2 gave 2 × 200 and 2 × 409 every time; offers went to the 5 nearest online, active couriers within 3 km (far, offline and blocked left out); `fd:offer:{id}` had TTL 45; reoffer offered new couriers only, expired offers older than 45 s, skipped a full bicycle and refused an order with a courier; reject gave the stock back, refunded MB WAY and wrote the history. No 5xx. ruff and pytest passed.
- **Mistakes caught:** the first version subtracted a `timedelta` from `text("now()")`, which raised a 500 on reoffer; changed to `func.now()`. The AI first made a new list of kitchen statuses instead of reusing `ACTIVE_KITCHEN_STATUSES`.
