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
from app.models.offers import OFFER_TTL_SECONDS
from app.models.orders import Order
from app.services.offers import offer_key
from app.services.ranking import RANK_TTL_SECONDS, bucket_key, recent_deliveries
from app.services.stock import stock_expire_at, stock_key
from app.services.tracking import (
    TRACK_TTL_SECONDS,
    track_fields,
    track_key,
    track_rows,
)


def rebuild_offers() -> int:
    """A: fd:offer:{offer_id} for offers still pending in PG, with the remaining TTL.

    Only offers younger than 45 s: older ones are invalid even if PG still says
    `pending` (lazy expiry), so they must not come back. Each key gets the seconds it
    has left, not a fresh 45, so a rebuild never makes an offer live longer.
    """
    with SessionLocal() as session:
        rows = session.execute(
            text("""
                SELECT f.id, f.order_id, f.courier_id, o.restaurant_id,
                       ceil(extract(epoch FROM f.sent_at + make_interval(secs => :ttl)
                                               - now()))::int AS ttl_left
                  FROM delivery_offers f
                  JOIN orders o ON o.id = f.order_id
                 WHERE f.outcome = 'pending'
                   AND f.sent_at > now() - make_interval(secs => :ttl)
            """),
            {"ttl": OFFER_TTL_SECONDS},
        ).all()
    # HSET + EXPIRE in one MULTI per key, as the app writes them: never a key without TTL.
    pipe = client.pipeline(transaction=True)
    for offer_id, order_id, courier_id, restaurant_id, ttl_left in rows:
        key = offer_key(offer_id)
        pipe.delete(key)
        pipe.hset(
            key,
            mapping={
                "order_id": order_id,
                "courier_id": courier_id,
                "restaurant_id": restaurant_id,
            },
        )
        pipe.expire(key, max(ttl_left, 1))
    pipe.execute()
    return len(rows)


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
