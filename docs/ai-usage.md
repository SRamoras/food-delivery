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
