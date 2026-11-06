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
