# Runbook: backup and recovery

How the group would recover from losing each engine. PostgreSQL is the source of truth: MongoDB reports and Redis keys are rebuilt from it, so it is restored first.

Sections still to be written by their owners are marked *(to do: name)*.

## PostgreSQL

### 1. What is backed up, how often, with which tool, where

| What | How often | Tool | Where |
|---|---|---|---|
| The whole `food_delivery` database (schema, data, grants) | Daily, at 04:00 (the quietest hour) | `pg_dump -Fc` as `fd_owner` | `backups/pg/dumps/` on the host, then copied off the machine |
| Write-ahead log (every committed change) | Continuously, one segment at least every 60 s | `archive_command` (WAL archiving) | `backups/pg/wal/` on the host, then copied off the machine |
| Physical base backup (starting point for WAL replay) | Weekly | `pg_basebackup` | `backups/pg/base/` on the host, then copied off the machine |

- **What is not backed up:** roles and passwords. `scripts/setup.sh` creates them from `.env`, which is kept out of Git (store it in the group's password manager).
- **What WAL archiving needs:** two changes to the `postgres` service in `compose.yml`. They are not active in the development setup:

```yaml
    command: ["postgres", "-c", "log_statement=${PG_LOG_STATEMENT:-none}",
              "-c", "wal_level=replica",
              "-c", "archive_mode=on",
              "-c", "archive_timeout=60",
              "-c", "archive_command=test ! -f /backups/wal/%f && cp %p /backups/wal/%f"]
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./backups/pg:/backups
```

- `archive_timeout=60` forces a new WAL segment at least once a minute, so at most about one minute of commits waits outside the archive.
- `test ! -f` refuses to overwrite a segment that is already archived.

### 2. Commands, in order

**Daily logical backup** (tested on the seeded data: 72 MB, about 6 s):

```bash
mkdir -p backups/pg/dumps
docker compose exec -T postgres pg_dump -U fd_owner -d food_delivery -Fc \
  > backups/pg/dumps/food_delivery_$(date +%F).dump
```

**Weekly base backup** (with WAL archiving on):

```bash
docker compose exec -T postgres mkdir -p /backups/base /backups/wal
docker compose exec -T postgres pg_basebackup -U postgres \
  -D /backups/base/$(date +%F) -Ft -z -Xs
```

**Restore A: from the last daily dump.** Use it for a lost or corrupted database when losing up to a day is acceptable, or to recover one table into a copy.

```bash
# 1. Stop the api so nothing writes during the restore.
docker compose stop api
# 2. Drop the broken database (as the superuser).
docker compose exec -T postgres psql -U postgres -c "DROP DATABASE IF EXISTS food_delivery"
# 3. Recreate roles, database and btree_gist. setup.sh would also run the
#    migrations, which would create empty tables, so run only its superuser part
#    (step 1 of scripts/setup.sh), or create them by hand:
docker compose exec -T postgres psql -U postgres -c "CREATE DATABASE food_delivery OWNER fd_owner"
docker compose exec -T postgres psql -U postgres -d food_delivery -c "CREATE EXTENSION btree_gist"
docker compose exec -T postgres psql -U postgres -c "REVOKE ALL ON DATABASE food_delivery FROM PUBLIC" \
  -c "GRANT CONNECT ON DATABASE food_delivery TO fd_app, fd_readonly"
# 4. Restore as the owner. The dump carries tables, data, constraints, indexes,
#    grants (including the REVOKE on order_status_history) and alembic_version.
#    --no-comments: the extension's comment can only be set by the superuser.
docker compose exec -T postgres pg_restore -U fd_owner -d food_delivery \
  --no-comments --exit-on-error < backups/pg/dumps/food_delivery_YYYY-MM-DD.dump
# 5. Start the api again.
docker compose start api
```

**Restore B: point in time, from a base backup + WAL.** Use it for the RPO target. These steps are written for PostgreSQL 17 and have not been run as a drill.

```bash
# 1. Stop everything that uses PostgreSQL, and PostgreSQL itself.
docker compose stop api postgres
# 2. In a one-off container with the same volumes: keep the broken data aside,
#    unpack the base backup, and point recovery at the WAL archive.
docker compose run --rm --no-deps --entrypoint bash postgres -c '
  set -e
  D=/var/lib/postgresql/data
  # $D is the volume mount point: move its contents, not the directory itself.
  OLD=/backups/broken/data-$(date +%s) && mkdir -p $OLD && mv $D/* $OLD/
  tar -xzf /backups/base/YYYY-MM-DD/base.tar.gz -C $D
  tar -xzf /backups/base/YYYY-MM-DD/pg_wal.tar.gz -C $D/pg_wal
  echo "restore_command = '\''cp /backups/wal/%f %p'\''" >> $D/postgresql.auto.conf
  # Optional: stop just before the mistake, then become a normal server.
  # echo "recovery_target_time = '\''2026-11-10 14:05:00+00'\''" >> $D/postgresql.auto.conf
  # echo "recovery_target_action = '\''promote'\''" >> $D/postgresql.auto.conf
  touch $D/recovery.signal
  chown -R postgres:postgres $D && chmod 700 $D
'
# 3. Start PostgreSQL: it replays the archived WAL, then accepts connections.
docker compose up -d postgres
docker compose logs -f postgres     # wait for "database system is ready to accept connections"
docker compose start api
```

**After either restore, rebuild what is derived from PostgreSQL:**

```bash
uv run python mongodb/export_reports.py   # report collections
uv run python redis/rebuild.py            # stock, tracking, ranking keys
uv run python redis/verify.py             # exit 0 = Redis matches the sources
```

### 3. How to check the restore

1. **Row counts.** Compare them with the counts printed by the last backup run, or with the old server if it is still readable:
   ```bash
   docker compose exec -T postgres psql -U postgres -d food_delivery -c "
     SELECT (SELECT count(*) FROM orders) AS orders, (SELECT count(*) FROM order_lines) AS lines,
            (SELECT count(*) FROM payments) AS payments, (SELECT count(*) FROM order_status_history) AS history,
            (SELECT max(created_at) FROM orders) AS last_order"
   ```
   `last_order` shows how far the restore reached, so how much was lost.
2. **Schema version:** `SELECT version_num FROM alembic_version;` must be the head of `postgres/migrations/versions/`.
3. **Constraints and privileges came back:**
   - `SELECT count(*) FROM pg_constraint WHERE connamespace = 'public'::regnamespace;` must match the count before the loss (103 at the time of writing);
   - `fd_app` must still have only `INSERT, SELECT` on `order_status_history`:
     ```sql
     SELECT privilege_type FROM information_schema.role_table_grants
      WHERE grantee = 'fd_app' AND table_name = 'order_status_history';
     ```
4. **The app works:**
   - `curl http://127.0.0.1:8000/health` answers OK;
   - placing one order from `/docs` works;
   - `redis/verify.py` exits 0.

Restore A was tested into a scratch database on the seeded data. Orders, lines, payments, `alembic_version`, the 103 constraints and the history grant all matched the original.

### 4. RTO and RPO

- **RPO: at most 1 minute.**
  - **Why:** PostgreSQL holds the payments, refunds and orders. Losing an hour means customers who paid, or were refunded, with no record of it, and orders a restaurant is cooking that no longer exist.
  - **Why the daily dump is not enough:** a daily `pg_dump` alone can lose up to 24 hours, which this business cannot accept. Continuous WAL archiving with `archive_timeout=60` can.
  - **What the daily dump is for:** it stays as a second, independent copy, and is the easiest way to recover one table.
- **RTO: 30 minutes.**
  - **What it covers:** stopping the api, unpacking the base backup, replaying at most a week of WAL, rebuilding Redis and the Mongo reports, and checking.
  - **Measured parts:** the logical restore of the current data took about 6 s, and the derived stores rebuild in seconds to minutes.
  - **Why 30 minutes is acceptable:** while PostgreSQL is down, no order can be placed. Half an hour at dinner time is a real loss, but recoverable. Making it faster would need a standby server, which is out of scope here.

### 5. What is lost for good

- **Recent commits:** whatever was committed after the last archived WAL segment, at most about 1 minute. With restore A, everything since the last dump.
- **PostgreSQL is the source of truth, so nothing else can give that data back.** The orders, payments and status changes of that window are gone. The payment provider's records (simulated here) would be the only way to find charges with no order.
- **What is not lost, because it is rebuilt from PostgreSQL afterwards:** the Redis stock, tracking and ranking keys and the MongoDB report collections.
- **What is not covered here:** live Redis state (who is online, pending offers) and the MongoDB position trail are in the Redis and MongoDB sections.

## MongoDB

*(to do: jcleberfernandes.)*

## Redis

*(to do: SRamoras.)*
