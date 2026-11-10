"""Last-hour ranking: the restaurants with most delivered orders, per city, in Redis."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Row, text

from app.db import redis
from app.db.postgres import SessionLocal

# 65 minutes: a bucket must outlive the 60-minute window it can be part of; the extra
# 5 minutes cover clock differences. Older buckets then disappear on their own.
RANK_TTL_SECONDS = 3900
WINDOW_MINUTES = 60
TOP = 20


def bucket_key(city_id: int, moment: datetime) -> str:
    # UTC, not Lisbon: when the clocks go back, Lisbon repeats an hour, and two
    # different minutes would share one bucket.
    return f"fd:rank:{city_id}:{moment.astimezone(UTC):%Y%m%d%H%M}"


def window_keys(city_id: int, now: datetime) -> list[str]:
    """The 60 bucket keys of the last hour, this minute included."""
    return [
        bucket_key(city_id, now - timedelta(minutes=i)) for i in range(WINDOW_MINUTES)
    ]


def record_delivery(city_id: int, restaurant_id: int) -> None:
    """Count one delivered order in this minute's bucket. Call it after the PG commit.

    city_id is the restaurant's city. ZINCRBY and EXPIRE run in one MULTI, so a
    bucket never exists without its TTL.
    """
    key = bucket_key(city_id, datetime.now(UTC))
    pipe = redis.client.pipeline(transaction=True)
    pipe.zincrby(key, 1, restaurant_id)
    pipe.expire(key, RANK_TTL_SECONDS)
    pipe.execute()


def top_restaurants(city_id: int) -> list[tuple[int, int]]:
    """Return up to 20 (restaurant_id, deliveries) of the last 60 minutes, most first.

    ZUNION adds up the 60 per-minute buckets; missing buckets count as empty.
    """
    keys = window_keys(city_id, datetime.now(UTC))
    totals = redis.client.zunion(keys, withscores=True)
    ranked = sorted(totals, key=lambda pair: (-pair[1], int(pair[0])))
    return [(int(member), int(score)) for member, score in ranked[:TOP]]


# Deliveries by the restaurant's city, the same city record_delivery is given.
RECENT_DELIVERIES_SQL = text("""
SELECT z.city_id, o.restaurant_id, d.delivered_at
  FROM deliveries d
  JOIN orders o ON o.id = d.order_id
  JOIN restaurants r ON r.id = o.restaurant_id
  JOIN zones z ON z.id = r.zone_id
 WHERE o.status = 'delivered' AND d.delivered_at >= :since
""")


def recent_deliveries(now: datetime) -> list[Row]:
    """Deliveries in PG that fall in the 60 buckets ending at `now`.

    What the ranking should hold: redis/rebuild.py writes it, redis/verify.py checks it.
    """
    since = now.replace(second=0, microsecond=0) - timedelta(minutes=WINDOW_MINUTES - 1)
    with SessionLocal() as session:
        return list(session.execute(RECENT_DELIVERIES_SQL, {"since": since}))
