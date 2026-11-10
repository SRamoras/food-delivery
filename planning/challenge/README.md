# Group project

The group project closes the module. Each group of three students builds the databases and a small backend for one business, using PostgreSQL, MongoDB and Redis, each for the job it does best. There are three projects. They differ in the business and share every rule in this file:

| Project | Business | Brief |
|---------|----------|-------|
| A | Ticket sales for concerts, theatre and sport | [a-ticketing.md](a-ticketing.md) |
| B | Food delivery | [b-food-delivery.md](b-food-delivery.md) |
| C | Music streaming | [c-music-streaming.md](c-music-streaming.md) |

The technical focus of every project is **concurrency**: each brief names business rules that break when many requests arrive at the same moment, and your project has to prove that they hold.

Read this file first, then the brief of your project. When this file and a project brief seem to disagree, ask the trainer.

The examples in this file come from a gym that sells memberships and books classes, a business that is not one of the three projects. They show the format of what is asked, not the answer for your project.

## Contents

- [Timeline and delivery](#timeline-and-delivery)
- [Shared responsibility](#shared-responsibility)
- [Stack and how the project runs](#stack-and-how-the-project-runs)
- [Repository structure](#repository-structure)
- [Technical requirements](#technical-requirements)
- [Documentation](#documentation)
- [Git rules](#git-rules)
- [Responsible use of AI](#responsible-use-of-ai)
- [Grading](#grading)
- [Sessions 17 to 19](#sessions-17-to-19)
- [Going further](#going-further)
- [Delivery checklist](#delivery-checklist)

## Timeline and delivery

- The trainer assigns one project to each group.
- The project starts when the group receives its brief.
- You work on it outside class and during sessions 17 and 18.
- The delivery is the highest [SemVer](https://semver.org/) tag pushed to your repository on GitHub **before session 19 starts**. Any SemVer tag is valid (`v1.0.0`, `1.0.0`, `v1.2.3`). `v1.0` is not SemVer and does not count.
- Commits and tags pushed after session 19 starts are not graded. This deadline is earlier than the one for the individual exercises, which is the end of session 19.
- Session 19 is the demonstration and the individual technical discussion. See [Sessions 17 to 19](#sessions-17-to-19).

Create the tag on the commit you want graded and push it:

```bash
git tag -a v1.0.0 -m "Project delivery"
git push origin v1.0.0
```

## Shared responsibility

Every member is responsible for the whole project. Do not split the work by engine ("Ana does PostgreSQL, Rui does MongoDB, Marta does Redis"). Each member must write code and schema in the three engines and in the app; the [Git rules](#git-rules) check this.

In session 19 the trainer can ask any member about any file in the repository, usually in the engine where that member committed least. "Another member wrote that" is not an answer. Before the delivery, each member explains to the others the parts they did not write.

## Stack and how the project runs

The stack is your choice. The trainer recommends one of these:

- FastAPI with SQLAlchemy and Alembic, pymongo (or Motor) and redis-py
- Django (ORM and migrations), pymongo and redis-py

Next.js with Prisma and the official MongoDB and Redis drivers is also accepted, as in the session examples. Write the choice and the reason for it in the README.

Whatever the stack:

- **Everything runs with Docker Compose**: the three engines and the app (API, worker or both) are services in `compose.yml`.
- **The trainer has Docker and uv.** Every command in your README must work with only those two, either on the host with `uv run` (the database ports are published on `127.0.0.1`) or inside a service with `docker compose run --rm <service> ...`. If you chose Next.js, Node is also available.
- **The PostgreSQL schema lives in versioned migrations**: Alembic (recommended), Django migrations or Prisma Migrate. Applying all migrations to an empty database creates the whole schema. Anything the ORM does not express well (`CHECK` with several columns, `EXCLUDE`, partial indexes, triggers, grants) goes into a migration as raw SQL (`op.execute` in Alembic, `RunSQL` in Django, a hand-edited `migration.sql` in Prisma). A schema created by hand in `psql` or by `create_all()` does not count.
- **MongoDB validators and indexes are created by a script** in `mongodb/`, which can run more than once without failing.

The project uses the same ports as the module environment (5432, 27017, 6379). Stop the module environment (`docker compose down` in the module repository) before starting the project.

### From a clean clone

A person who has never seen the project must be able to run it with these commands, in this order:

```bash
cp .env.example .env
docker compose up -d
./scripts/setup.sh      # roles, migrations, MongoDB users, validators and indexes
./scripts/seed.sh       # PostgreSQL seed, MongoDB seed and report export, Redis rebuild
```

and then the concurrency test, with the command your README gives. If any other step is needed, the README must say so.

`scripts/setup.sh` runs in this order:

1. As the PostgreSQL superuser from `.env`: create the project database, the roles (owner, app, read-only) and any extension you need (`btree_gist` for `EXCLUDE` with equality, `pg_trgm` for text search). Creating roles needs a superuser, so this cannot be done inside a migration run by the owner.
2. As the owner role: apply every migration. Point Alembic, Django or Prisma at a separate connection URL for this (for example `MIGRATION_DATABASE_URL`), because the app role cannot create tables. The grants for the app and read-only roles go in a migration; `ALTER DEFAULT PRIVILEGES` makes them apply to tables created later.
3. As the MongoDB root user: create the app user, the collections with their validators, and the indexes.

`.env.example` lists every variable with a placeholder password, for example `DATABASE_URL` (app role), `MIGRATION_DATABASE_URL` (owner role), `READONLY_DATABASE_URL`, `MONGO_URL`, `MONGO_ROOT_URL` and `REDIS_URL`.

## Repository structure

One new repository per group on GitHub (not a fork of the module repository). The three members are collaborators, and the trainer gets read access with the GitHub account given in class.

The repository must have this structure at its root:

```
compose.yml
.env.example
.gitignore            includes .env
README.md
app/                  the mini app: API, worker, or both
postgres/             migrations, SQL files and the PostgreSQL seed
mongodb/              setup (validators, indexes), report export, aggregation pipelines, seed
redis/                Lua scripts, rebuild and verify scripts
scripts/              setup.sh, seed.sh, and any other helper
docs/                 the documents listed in Documentation
```

With Django or Prisma, the models and migrations stay where the framework puts them (for example `app/gym/models.py` and `app/gym/migrations/`, or `prisma/schema.prisma` and `prisma/migrations/`). In that case, list those paths in the README as the PostgreSQL paths. The trainer uses them, together with `postgres/`, to check commits.

You may add folders. You may not move the ones above.

## Technical requirements

Every requirement in this section is mandatory in the three projects. The project brief gives the business; you design how it is stored.

### PostgreSQL

PostgreSQL holds the data that must never be lost or contradict itself.

1. **Schema.** At least 10 tables, designed by you from the requirements of your brief, in third normal form. Any denormalisation is deliberate and written down in `docs/postgres.md`.
2. **Types.** `numeric` for money (never `float` or `real`), `timestamptz` for moments in time, `date` for calendar days, `text` unless a length limit is a real business rule, and enumerated values with a `CHECK` or a reference table.
3. **Keys and relationships.** Every table has a primary key. Every relationship has a foreign key with an `ON DELETE` behaviour you chose and can justify. N:N relationships have an association table.
4. **Constraints.** Each brief has a section "Where the rules are enforced" with two lists. Every rule in the first list must be enforced by PostgreSQL itself, with `NOT NULL`, `UNIQUE`, `CHECK`, `EXCLUDE`, a partial unique index, a trigger, or privileges (`REVOKE UPDATE, DELETE`). Every rule in the second list can be enforced in PostgreSQL or in the app; `docs/postgres.md` says where each one is enforced and why. Enforcing more rules in the database than the first list asks for is a good extension.
5. **Indexes.** Every index exists for a reason you can name: the query it serves, or the constraint it backs. For at least 3 queries from the "Frequent queries" section of your brief, show `EXPLAIN (ANALYZE, BUFFERS)` without and with the index, on the seeded data, in `docs/postgres.md`. To get the plan without the index after the migrations have created it, drop it inside a transaction and roll back:

   ```sql
   BEGIN;
   DROP INDEX gym_booking_member_idx;
   EXPLAIN (ANALYZE, BUFFERS) SELECT ...;
   ROLLBACK;
   ```

   An index created by a `PRIMARY KEY` or `UNIQUE` constraint does not count towards the 3. Also say which foreign keys you indexed and which you did not, and why.
6. **Critical transaction.** The concurrent flows of your brief run in one PostgreSQL transaction each (or one transaction plus an atomic Redis step, if that is your design). `docs/concurrency.md` explains the isolation level and the locks they use.
7. **Roles.** Three roles: an owner role that runs the migrations and owns the schema; an app role that the app uses, with only the privileges it needs (no superuser, no `CREATE` on the schema, no `DROP`, no `UPDATE` or `DELETE` on tables that are append-only in your design); and a read-only role for reports and exports. See [From a clean clone](#from-a-clean-clone) for who creates them.

### MongoDB

MongoDB holds documents that are read as a whole, change shape from case to case, or are produced in large numbers.

1. **Collections.** At least 3 collections. Each brief has a section "MongoDB collections" that names the collections you must have and the data you decide about. For each collection, `docs/mongodb.md` says what it holds, why it is in MongoDB and not in PostgreSQL, and whether it is a source of truth or derived data.
2. **Report data.** Most report data comes from PostgreSQL. A script in `mongodb/` (the report export) reads PostgreSQL with the read-only role and writes the derived collections your pipelines run on, as in the frozen report of session 14. `seed.sh` runs it after the PostgreSQL seed, and it can be run again at any time to refresh the reports. You decide the shape of the exported documents.
3. **Validation.** Every collection has a `$jsonSchema` validator with `validationLevel: "strict"` and `validationAction: "error"`, with the required fields, their types and, where they apply, enumerated values and ranges.
4. **Embed or reference.** For every relationship inside or between documents, `docs/mongodb.md` says whether it is embedded or referenced, and why (how it is read, how big it grows, how often it changes).
5. **Indexes.** Indexes for the queries the app and the pipelines run, including a TTL index on every collection your brief says expires. Show `explain("executionStats")` for at least one query without and with its index.
6. **Aggregation pipelines.** At least 3 pipelines that answer the report questions of your brief, saved as files in `mongodb/`, each with the question it answers and a sample of its output in `docs/mongodb.md`.
7. **User.** The app connects with a user that has `readWrite` on the project database only. The root user is used only by `scripts/setup.sh`.

### Redis

Redis holds data that changes many times per second, expires, or must be read in under a millisecond.

1. **Keys.** Every key follows a naming convention written in `docs/redis.md` (for example `gym:{gym_id}:occupancy`). For each key pattern, `docs/redis.md` gives: the data structure, an example value, the TTL and the reason for it (or the reason it has none), the commands the app uses on it, and its class: source of truth, derived, or ephemeral (as in session 16).
2. **TTL.** Every key that holds temporary data has a TTL set atomically with the write: in the same command (`SET ... EX`), or in the same `MULTI`/`EXEC`. A crash between two separate commands must not leave a key that never expires.
3. **Rebuild and verify.** `redis/` has a rebuild script that recreates every derived key from PostgreSQL or MongoDB after a `FLUSHALL`, and a verify script that compares Redis with the source and exits with 1 if they differ, 0 otherwise. `seed.sh` populates Redis by running the rebuild, not by writing to Redis directly.
4. **Cache evidence.** For every flow your brief marks as "read from Redis", `docs/redis.md` shows that a repeated request reads only Redis: the output of `MONITOR` in `redis-cli` or an app log line, next to the PostgreSQL log (`log_statement = 'all'`) showing no query for that request.
5. **Authentication** with a password (`requirepass`), read from `.env`.

Limits "per minute" or "per hour" in the briefs can use a fixed window that starts at the first event: `INCR` the counter and, if the result is 1, set its `EXPIRE`, both in one `MULTI`/`EXEC` or Lua script. A sliding window is a good extension.

### Concurrency

1. The app exposes the concurrent flows named in your brief.
2. **Fixtures.** The test creates the starting state it needs (customers, a nearly full section, a playlist with 490 tracks, ...) and resets it before each run, so it can run any number of times in a row. The setup may write directly to the database; only the contested requests must go through the API.
3. **Responses.** A request that succeeds returns a 2xx. A request refused because of the rule returns a 4xx you choose (409 is the usual one) and a message. In real mode, any 5xx counts as a failure of the test.
4. **Output.** The script prints, for each scenario: the mode, how many requests succeeded, how many were refused, how many failed with 5xx, and whether the rule holds in the data. It exits with 1 if the rule is broken or, in real mode, if any request returned 5xx; with 0 otherwise.
5. `docs/concurrency.md` shows the output of three runs per scenario in each mode. Two scenarios give 12 outputs.

### Mini app

The mini app is the backend of the business. It does not need to be complete, and it needs no frontend, but it must represent what the business does:

1. It implements every flow marked as mandatory in your brief.
2. It uses the three engines in those flows, as your design and `docs/architecture.md` describe.
3. It runs as one or more services in `compose.yml` (an API, a worker, or both).
4. Every endpoint is documented, either by the framework's OpenAPI page or by a list in the README with a `curl` example for each one.
5. Every query is parameterised, in SQL and in MongoDB. No f-strings or string concatenation with input from a request.
6. **No authentication.** The briefs store a password hash so the schema is realistic, but the app needs no login. Each request says who is acting with an id in the path or the body, or an `X-User-Id` header. Choose one and use it everywhere.
7. **Time.** Every calendar day, opening hour, month and "today" is in the `Europe/Lisbon` time zone. Store moments as `timestamptz`.
8. **State that changes with time** (a hold that expires, a performance that starts, a daily stock that resets) can be computed when it is read, updated by a worker service in `compose.yml`, or both. `docs/architecture.md` says which, for each case.
9. Payments are simulated. The brief says how.

### Seed

1. `scripts/seed.sh` fills PostgreSQL and MongoDB with the volumes given in your brief, runs the report export, then runs the Redis rebuild.
2. The seed is deterministic: it uses a fixed random seed, so two clean clones produce the same data. Dates are relative to the day the seed runs ("the last 12 months", "the last 7 days"), so that data with a TTL is not deleted as soon as it is loaded.
3. The data respects every constraint and business rule of the brief. The seed does not disable constraints or triggers to load faster.
4. The data is realistic, not uniform: some customers order much more than others, some items are much more popular. Reports with every value equal teach nothing.
5. The full seed runs in under 5 minutes on a recent laptop. Use `COPY` or batch inserts, as in session 04.

### Security

1. The app connects to PostgreSQL with the app role, to MongoDB with the `readWrite` user, and to Redis with the password. Never as `postgres` or `root`.
2. No secrets in Git. The repository has `.env.example` with placeholder values, `.env` is in `.gitignore`, and `compose.yml` reads every password from `.env`. A password committed at any point in the history counts as committed, even if a later commit removes it.
3. Every query is parameterised (see [Mini app](#mini-app)).
4. `docs/architecture.md` has a security section listing the roles and users, what each one can do, and why.

### Backup and recovery

`docs/runbook.md` describes, for each engine, how the group would recover from losing it. The tools and the strategy are your decision. For each engine it gives:

1. What is backed up, how often, with which tool, and where the backups are kept. For Redis, whether you back it up or rebuild it, and why.
2. The exact commands to back up and to restore, in the order they run.
3. How you verify that a restore worked (counts, a known query, the Redis verify script).
4. The **RTO** (how long a restore may take) and **RPO** (how much data may be lost) targets, estimated and justified by the business of your brief. For example, for the gym: "losing one hour of class bookings is annoying, but losing one hour of membership payments means members who paid and have no record of it, so the RPO for PostgreSQL is at most 5 minutes, which a daily `pg_dump` cannot meet".
5. What is lost for good if that engine is lost, and whether the business can live with it.

You do not have to run a disaster drill, but the commands in the runbook must be correct, and you may be asked about them in session 19.

## Documentation

These documents are mandatory, with these exact names. Write them in English.

| File | Contents |
|------|----------|
| `README.md` | What the project does in a few sentences. How to run it from a clean clone and how to run the concurrency test. The stack and why. The ER diagram of PostgreSQL in Mermaid. The list of endpoints or a link to the OpenAPI page, and how a request says who is acting. The PostgreSQL paths if you use Django or Prisma. The authors table (below). A link to every document in `docs/`. |
| `docs/postgres.md` | Every table: what it represents and why it exists. Every constraint, index and trigger: the rule or query it serves. Both lists of "Where the rules are enforced" from your brief, with how and where each rule is enforced. Denormalisations and why. The `EXPLAIN` evidence. The roles. |
| `docs/mongodb.md` | Every collection: what it holds, why in MongoDB, source of truth or derived, an example document, the validator, embed or reference decisions, indexes (including TTL) with the reason. The report export: what it reads and writes. Every pipeline with its question and a sample of its output. |
| `docs/redis.md` | Every key pattern with the fields listed in [Redis](#redis). The cache evidence. The rebuild and verify scripts: what they read and how to run them. Persistence and memory settings, and why. |
| `docs/architecture.md` | The source-of-truth table: every kind of data, the engine that owns it, the engines that hold copies, which copy wins when they disagree, and what is lost if each engine is lost. How the app moves data between the engines in each flow (a sequence diagram in Mermaid is welcome). What happens if a write to the second engine fails after the first one succeeded. How each state that changes with time is handled. The security section. |
| `docs/runbook.md` | See [Backup and recovery](#backup-and-recovery). |
| `docs/ai-usage.md` | See [Responsible use of AI](#responsible-use-of-ai). |

The authors table in the README has one row per member:

| Name | GitHub user | Git author email |
|------|-------------|------------------|
| Ana Silva | anasilva | ana.silva@example.com |

The email must be the one in `git config user.email` on every machine the member commits from. The trainer checks commits by this email.

## Git rules

### Every member commits

Each member must have commits of their own, with real work, in each of these four areas:

| Area | Paths |
|------|-------|
| PostgreSQL | `postgres/`, plus the PostgreSQL paths in the README if you use Django or Prisma |
| MongoDB | `mongodb/` |
| Redis | `redis/` |
| App | `app/` |

A commit counts in every area whose files it changes. With Django, a commit that changes `app/gym/migrations/` counts for both PostgreSQL and App. Commits in `docs/`, `tests/`, `scripts/` or the root are welcome but do not count towards any area.

A commit is **trivial**, and does not count, when it only changes whitespace, formatting, comments, file names, or generated files (lock files, files written by a tool without your edits).

What counts and what does not:

| Commit | Counts? |
|--------|---------|
| `a1b2c3d` by Ana, "Add CHECK that a membership ends after it starts", changes `postgres/migrations/0004_membership.py` | Yes, for Ana, in PostgreSQL |
| `e4f5a6b` by Rui, "Merge pull request #12 from group/class-booking" | No. Merge commits never count, for anyone |
| `c7d8e9f` by Rui, with a `Co-authored-by: Ana` line | Only for Rui. Co-author lines do not count |
| A squash commit made by GitHub when merging a PR | Not allowed (see below) |
| `b1c2d3e` by Marta, "Explain occupancy keys", changes only `docs/redis.md` | No area: `docs/` does not count |
| `f4e5d6c` by Ana, "Run black", only formatting | No. Trivial |
| A commit whose author email is not in the authors table | No |

### Pull requests and merges

You can push to `main` directly or work in branches with pull requests. Both are fine. When you merge a pull request, use **Create a merge commit** or **Rebase and merge**. **Squash and merge is forbidden**, because it replaces everyone's commits with one commit authored by whoever merged. Turn it off in the repository: Settings, General, Pull Requests, untick "Allow squash merging".

Do not rewrite the history of `main` (`git push --force`) after a member has pushed to it.

### How the trainer checks

With the tag you delivered (here `v1.0.0`) and each member's email from the authors table:

```bash
git log v1.0.0 --no-merges --author="ana.silva@example.com" --format="%h %an %ad %s" --date=short -- postgres/
```

To count one member's commits per area (add your PostgreSQL paths to the first line if you use Django or Prisma, for example `"postgres/ app/gym/migrations/"`):

```bash
for area in "postgres/" "mongodb/" "redis/" "app/"; do
  printf "%-12s " "$area"
  git log v1.0.0 --no-merges --author="ana.silva@example.com" --oneline -- $area | wc -l
done
```

Run the same commands on your own repository before the delivery. If a number is 0, the member has no commit in that area. The trainer then reads the commits to exclude trivial ones.

### Penalties

- A member with no commit of their own in one of the four areas loses **2 points** from their individual mark, for each area missing. This adds to the modifier of the technical discussion.
- A member with no commit of their own at all, merges and co-author lines excluded, does not receive a project mark.

## Responsible use of AI

You can and should use AI tools. You are responsible for everything they produce that ends up in your repository: every line, every constraint, every index. In session 19, "the AI wrote it" is not an answer.

`docs/ai-usage.md` has one entry per relevant use. Every entry has:

- **Who**: the member who used it.
- **Tool**: name and, if you know it, model.
- **For what**: the task, and the files or the part of the project affected.
- **Outcome**: what you kept as it came, what you changed, and what you rejected, with the reason.
- **Verification**: how you checked it (a test, an `EXPLAIN`, the official documentation, a review by another member).
- **Mistakes caught**: errors in the AI output that you found, if any.

Example, from the gym:

> **Who:** Rui Costa. **Tool:** Claude.
> **For what:** first draft of the class booking script, `redis/book_class.lua`.
> **Outcome:** kept the structure. Changed the key names to our convention. Rejected a version that set the TTL of the waiting-list key in a second command after `RPUSH`, because a crash between the two would leave a key that never expires.
> **Verification:** ran the concurrency test 3 times against the script; read the `EVAL` and `EXPIRE` pages of the Redis documentation.
> **Mistakes caught:** the draft used `KEYS class:*` to clean up old bookings, which our rules forbid.

The file ends with this declaration, with the names of the three members:

> We, Ana Silva, Rui Costa and Marta Reis, declare that we understand and can explain all the code, schemas and documents in this repository, including those produced with the help of AI tools.

## Grading

The project is graded by the trainer, out of 20.

| Criterion | Points | What is checked |
|-----------|--------|-----------------|
| PostgreSQL | 7 | Schema covers the brief, types, keys and relationships, the rules of "Where the rules are enforced", indexes with evidence, migrations from an empty database, critical transactions, roles |
| MongoDB | 3 | Mandatory collections and why they are in MongoDB, report export, validators, embed or reference decisions, indexes including TTL, the 3 pipelines |
| Redis | 2 | Key design, TTLs set atomically, atomic operations, cache evidence, rebuild and verify |
| Concurrency | 2 | Naive version showing the race, real version holding the rule, test through the API with fixtures and the required number of requests, explanation |
| Mini app | 2 | Mandatory flows, integration of the three engines, runs in Docker Compose |
| Security and runbook | 2 | Roles and users with least privilege, no secrets in Git, parameterised queries, runbook with commands, RTO and RPO justified |
| Documentation | 2 | Every mandatory document present, complete and accurate, including `ai-usage.md` |
| **Group mark** | **20** | |

Each member's individual mark is:

```
individual mark = group mark + discussion modifier (−4 to +2) − commit penalties
```

limited to the range 0 to 20. The discussion modifier comes from the individual questions in session 19. The commit penalties are in [Git rules](#penalties).

If the trainer cannot run `setup.sh` or `seed.sh` from a clean clone by following the README, the parts that need a running system (concurrency, mini app, cache evidence, pipelines) are graded on the evidence in `docs/` only, with at most half of their points.

## Sessions 17 to 19

- **Session 17**: work session. Go through the [delivery checklist](#delivery-checklist), run the concurrency test against the full app and fix what fails.
- **Session 18**: work session. Finish the documentation, check that each member has commits in every area, and have each member explain to the others the parts they did not write.
- **Session 19**: delivery.
  1. Demonstration, 10 minutes per group, from a clean clone of the delivered tag: start the project, run the concurrency test against the naive version and against the real version, and explain the mechanism. If the seed takes more than a couple of minutes, run it from the clean clone before your slot starts.
  2. Individual technical discussion. The trainer asks each member about any part of the project, usually in the engine they contributed least to. Typical questions: why does this constraint or index exist; what happens with two simultaneous requests here; what is lost if Redis disappears; how do you restore MongoDB; why is this embedded and that referenced; what did the AI get wrong.

## Going further

The requirements above and in your brief are the minimum. Once they are met, make the project more complete: more flows, more business rules enforced in the database, better reports, clearer documentation of the business. Each brief ends with ideas. Document every extension in the README and in the relevant document in `docs/`. Every extension follows the same rules as the rest of the project, including the commit rules.

## Delivery checklist

- [ ] The project runs from a clean clone with the commands of [From a clean clone](#from-a-clean-clone), using only Docker and uv or node.
- [ ] All migrations apply to an empty database, run by the owner role.
- [ ] The seed loads the volumes of the brief in under 5 minutes, with every constraint on, and runs the report export and the Redis rebuild.
- [ ] Every mandatory flow of the brief works through the app.
- [ ] Every rule in the first list of "Where the rules are enforced" is enforced by PostgreSQL.
- [ ] `FLUSHALL`, then the rebuild, then the verify script exits with 0.
- [ ] The cache evidence is in `docs/redis.md`.
- [ ] The 3 MongoDB pipelines run and their output is in `docs/mongodb.md`.
- [ ] At least 3 PostgreSQL queries have `EXPLAIN (ANALYZE, BUFFERS)` without and with the index, none of them served only by a primary key or unique constraint.
- [ ] The app does not connect as `postgres` or `root`.
- [ ] `git log -p | grep -i password` shows no real password.
- [ ] Every document in [Documentation](#documentation) exists and is complete, including the declaration in `docs/ai-usage.md`.
- [ ] Each member has at least one non-trivial commit in each of the four areas (run the commands in [How the trainer checks](#how-the-trainer-checks)).
- [ ] Squash merging is turned off.
- [ ] A SemVer tag is pushed before session 19 starts.