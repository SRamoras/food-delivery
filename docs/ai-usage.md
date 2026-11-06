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
