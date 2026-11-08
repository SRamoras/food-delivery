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
