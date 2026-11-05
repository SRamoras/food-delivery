#!/usr/bin/env bash
# Creates everything the app needs, in order:
#   1. as the postgres superuser: database, roles, extensions
#   2. as fd_owner: Alembic migrations (tables, constraints, grants)
#   3. as the mongo root user: app user, collections, validators, indexes
# Safe to run any number of times (every step is "create if missing").
set -euo pipefail

cd "$(dirname "$0")/.."

# --- environment -------------------------------------------------------------
# Load .env without overriding variables that are already set. The dev container
# sets the URLs with service names (postgres, mongo) instead of 127.0.0.1; those win.
if [[ -f .env ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    [[ -z "${!key+x}" ]] && export "$key=$value"
  done < .env
fi

for var in FD_OWNER_PASSWORD FD_APP_PASSWORD FD_READONLY_PASSWORD; do
  [[ -n "${!var:-}" ]] || { echo "error: $var is not set (cp .env.example .env)" >&2; exit 1; }
done

# --- wait for the databases ----------------------------------------------------
# Right after `docker compose up -d` the containers may still be starting.
echo "==> waiting for postgres and mongo"
for _ in $(seq 1 60); do
  if docker compose exec -T postgres pg_isready -U postgres -q \
     && docker compose exec -T mongo mongosh --quiet --eval "db.adminCommand('ping').ok" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose exec -T postgres pg_isready -U postgres -q || { echo "error: postgres is not ready" >&2; exit 1; }

# --- 1. PostgreSQL, as the superuser ---------------------------------------------
# psql runs inside the postgres container (no psql needed on the host).
# Passwords go in as environment variables (-e NAME, value taken from this shell),
# never on the command line, so they do not show up in `ps`. \getenv reads them and
# :'var' quotes them as SQL literals (no injection, any character allowed).
echo "==> postgres: roles, database, extensions"
docker compose exec -T \
  -e FD_OWNER_PASSWORD -e FD_APP_PASSWORD -e FD_READONLY_PASSWORD \
  postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q <<'SQL'
\getenv owner_pw FD_OWNER_PASSWORD
\getenv app_pw FD_APP_PASSWORD
\getenv ro_pw FD_READONLY_PASSWORD

-- CREATE ROLE has no IF NOT EXISTS: build the statement only when the role is
-- missing and run it with \gexec. ALTER ROLE then (re)sets the password every run,
-- so changing a password in .env and re-running setup.sh applies it.
SELECT 'CREATE ROLE fd_owner' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fd_owner') \gexec
SELECT 'CREATE ROLE fd_app' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fd_app') \gexec
SELECT 'CREATE ROLE fd_readonly' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'fd_readonly') \gexec

-- None of them can create databases or roles; only fd_owner will own objects.
ALTER ROLE fd_owner    WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'owner_pw';
ALTER ROLE fd_app      WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_pw';
ALTER ROLE fd_readonly WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'ro_pw';
-- Defence in depth: even if a write grant is added by mistake, fd_readonly's
-- transactions are read-only.
ALTER ROLE fd_readonly SET default_transaction_read_only = on;

-- CREATE DATABASE cannot run inside a transaction or DO block, hence \gexec again.
-- fd_owner owns the database, so it also owns the public schema (PostgreSQL 15+)
-- and can create tables there; fd_app and fd_readonly cannot.
SELECT 'CREATE DATABASE food_delivery OWNER fd_owner'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'food_delivery') \gexec

-- Only our three roles can connect.
REVOKE ALL ON DATABASE food_delivery FROM PUBLIC;
GRANT CONNECT ON DATABASE food_delivery TO fd_app, fd_readonly;

\connect food_delivery
-- Extensions need the superuser. btree_gist: lets a GiST index mix `=` on plain
-- columns with `&&` on ranges, for the EXCLUDE on opening hours.
CREATE EXTENSION IF NOT EXISTS btree_gist;
SQL

# --- 2. PostgreSQL, as fd_owner: migrations ----------------------------------------
# Alembic's env.py connects with MIGRATION_DATABASE_URL (fd_owner).
echo "==> postgres: alembic upgrade head (fd_owner)"
uv run alembic -c postgres/alembic.ini upgrade head

# --- 3. MongoDB, as root ---------------------------------------------------------
if [[ -f mongodb/setup.py ]]; then
  echo "==> mongo: users, collections, validators, indexes (root)"
  uv run python mongodb/setup.py
else
  echo "==> mongo: skipped (mongodb/setup.py not created yet)"
fi

echo "==> setup done"
