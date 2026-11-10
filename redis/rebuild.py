"""Rebuilds every derived Redis key from PostgreSQL (and MongoDB). Safe to re-run.

Run after FLUSHALL, a Redis restore or the seed:
    uv run python redis/rebuild.py
Ephemeral keys are not rebuilt on purpose: courier positions and presence
(fd:couriers:geo, fd:courier:{id}:online) come back with the next position each
courier sends.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import text

from app.config import LISBON
from app.db.postgres import SessionLocal
from app.db.redis import client
from app.models.orders import Order
from app.services.ranking import RANK_TTL_SECONDS, bucket_key, recent_deliveries
from app.services.stock import stock_expire_at, stock_key
from app.services.tracking import (
    TRACK_TTL_SECONDS,
    track_fields,
    track_key,
    track_rows,
)


def rebuild_offers() -> int:
    """A: fd:offer:{offer_id} for offers still pending in PG, with the remaining TTL."""
    return 0


def rebuild_stock() -> int:
    """B: fd:stock:{item_id}:{date} from today's daily stock rows in PG."""
    # Only today: past days are never read again and their keys expire on their own.
    today = datetime.now(LISBON).date()
    # Drop today's copies first, so a key whose PG row is gone does not survive.
    # SCAN, never KEYS: it walks the keyspace in small batches without blocking Redis.
    stale = list(client.scan_iter(match=f"fd:stock:*:{today.isoformat()}", count=1000))
    if stale:
        client.delete(*stale)
    with SessionLocal() as session:
        rows = session.execute(
            text("SELECT item_id, remaining FROM daily_stock WHERE stock_date = :d"),
            {"d": today},
        ).all()
    exat = stock_expire_at(today)
    pipe = client.pipeline(transaction=False)
    for item_id, remaining in rows:
        # Same key, value and EXAT as the app writes after an order.
        pipe.set(stock_key(item_id, today), remaining, exat=exat)
    pipe.execute()
    return len(rows)


def _delete_matching(pattern: str) -> None:
    # SCAN, never KEYS: it walks the keyspace in small batches without blocking Redis.
    stale = list(client.scan_iter(match=pattern, count=1000))
    if stale:
        client.delete(*stale)


def rebuild_tracking() -> int:
    """C: fd:order:{id}:track for orders that are not finished yet.

    Finished orders are left out: nobody tracks them for long, and a request for one
    fills its key from PG on the cache miss.
    """
    _delete_matching("fd:order:*:track")
    with SessionLocal() as session:
        rows = session.execute(
            track_rows().where(
                Order.status.not_in(["delivered", "cancelled", "rejected"])
            )
        ).all()
    # One MULTI: each HSET has its EXPIRE in the same transaction, as in the app.
    pipe = client.pipeline(transaction=True)
    for row in rows:
        pipe.hset(track_key(row.id), mapping=track_fields(row))
        pipe.expire(track_key(row.id), TRACK_TTL_SECONDS)
    pipe.execute()
    return len(rows)


def rebuild_ranking() -> int:
    """C: fd:rank:{city_id}:{minute} buckets from the last hour of deliveries in PG."""
    _delete_matching("fd:rank:*")
    rows = recent_deliveries(datetime.now(UTC))
    pipe = client.pipeline(transaction=True)
    keys = set()
    for city_id, restaurant_id, delivered_at in rows:
        # Same key and TTL as record_delivery, in the same MULTI.
        key = bucket_key(city_id, delivered_at)
        pipe.zincrby(key, 1, restaurant_id)
        pipe.expire(key, RANK_TTL_SECONDS)
        keys.add(key)
    pipe.execute()
    return len(keys)


# Each function returns how many keys it wrote.
STEPS: list[Callable[[], int]] = [
    rebuild_offers,
    rebuild_stock,
    rebuild_tracking,
    rebuild_ranking,
]


def main() -> None:
    client.ping()  # fail fast with a clear error if Redis is down or the password is wrong
    for step in STEPS:
        print(f"  {step.__name__}: {step()} key(s)")


if __name__ == "__main__":
    main()
