"""Last-hour ranking: the restaurants with most delivered orders, per city, in Redis."""

from datetime import UTC, datetime, timedelta

from app.db import redis

# 65 minutes: a bucket must outlive the 60-minute window it can be part of; the extra
# 5 minutes cover clock differences. Older buckets then disappear on their own.
RANK_TTL_SECONDS = 3900
WINDOW_MINUTES = 60
TOP = 20


def _bucket_key(city_id: int, moment: datetime) -> str:
    # UTC, not Lisbon: when the clocks go back, Lisbon repeats an hour, and two
    # different minutes would share one bucket.
    return f"fd:rank:{city_id}:{moment.astimezone(UTC):%Y%m%d%H%M}"


def record_delivery(city_id: int, restaurant_id: int) -> None:
    """Count one delivered order in this minute's bucket. Call it after the PG commit.

    ZINCRBY and EXPIRE run in one MULTI, so a bucket never exists without its TTL.
    """
    key = _bucket_key(city_id, datetime.now(UTC))
    pipe = redis.client.pipeline(transaction=True)
    pipe.zincrby(key, 1, restaurant_id)
    pipe.expire(key, RANK_TTL_SECONDS)
    pipe.execute()


def top_restaurants(city_id: int) -> list[tuple[int, int]]:
    """Return up to 20 (restaurant_id, deliveries) of the last 60 minutes, most first.

    ZUNION adds up the 60 per-minute buckets; missing buckets count as empty.
    """
    now = datetime.now(UTC)
    keys = [
        _bucket_key(city_id, now - timedelta(minutes=i)) for i in range(WINDOW_MINUTES)
    ]
    totals = redis.client.zunion(keys, withscores=True)
    ranked = sorted(totals, key=lambda pair: (-pair[1], int(pair[0])))
    return [(int(member), int(score)) for member, score in ranked[:TOP]]
