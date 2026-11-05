#!/usr/bin/env bash
# Loads the demo data, in dependency order. Run after setup.sh.
# Each step is a Python script owned by one member; a step whose file does not exist
# yet is skipped with a message, so the chain runs end to end from day one.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/_env.sh

run_step() {
  local owner="$1" file="$2"
  if [[ -f "$file" ]]; then
    echo "==> [$owner] $file"
    local start=$SECONDS
    uv run python "$file"
    echo "    done in $((SECONDS - start)) s"
  else
    echo "==> [$owner] $file: skipped (not written yet)"
  fi
}

# Order matters: each step needs the rows of the previous ones (foreign keys).
run_step C postgres/seed/catalogue.py   # cities, zones, fees, customers, restaurants, hours, menu
run_step B postgres/seed/orders.py      # orders, lines, payments, status history, daily stock
run_step A postgres/seed/couriers.py    # couriers, offers, deliveries (needs the orders)
run_step C postgres/seed/ratings.py     # ratings (needs delivered orders)
run_step A mongodb/seed.py              # courier position trail, last 7 days
run_step C mongodb/export_reports.py    # PG -> report collections
run_step A redis/rebuild.py             # every derived Redis key from PG/Mongo

# The course asks for the whole seed in under 5 minutes.
echo "==> seed done in $SECONDS s"
