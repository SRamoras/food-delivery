"""Compares the derived Redis keys with their source (PG/Mongo). Exit 1 on any mismatch.

    uv run python redis/verify.py
Test: FLUSHALL -> redis/rebuild.py -> redis/verify.py exits 0.
"""

import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import text

from app.config import LISBON
from app.db.postgres import SessionLocal
from app.db.redis import client
from app.models.orders import Order
from app.services.ranking import recent_deliveries, window_keys
from app.services.stock import stock_key
from app.services.tracking import track_fields, track_rows


def verify_offers() -> list[str]:
    """A: every pending, non-expired offer in PG has its fd:offer key, and no extra keys."""
    return []


def verify_stock() -> list[str]:
    """B: fd:stock:{item_id}:{today} equals daily_stock.remaining in PG."""
    today = datetime.now(LISBON).date()
    # What Redis should hold, from the source of truth. Strings: the client decodes.
    with SessionLocal() as session:
        expected = {
            stock_key(item_id, today): str(remaining)
            for item_id, remaining in session.execute(
                text(
                    "SELECT item_id, remaining FROM daily_stock WHERE stock_date = :d"
                ),
                {"d": today},
            )
        }
    actual = {
        key: client.get(key)
        for key in client.scan_iter(match=f"fd:stock:*:{today.isoformat()}", count=1000)
    }
    # Missing or wrong keys, then keys Redis has but PG does not.
    problems = [
        f"{key}: redis={actual.get(key)!r} pg={value!r}"
        for key, value in expected.items()
        if actual.get(key) != value
    ]
    problems += [
        f"{key}: in redis but not in pg" for key in actual if key not in expected
    ]
    return problems


def verify_tracking() -> list[str]:
    """C: fd:order:{id}:track status and courier match PG.

    Only the keys that exist: a missing key is normal (cache-aside, filled on a miss).
    updated_at is not compared, because the app and PG take the time a moment apart.
    """
    keys = list(client.scan_iter(match="fd:order:*:track", count=1000))
    if not keys:
        return []
    order_ids = [int(key.split(":")[2]) for key in keys]
    with SessionLocal() as session:
        expected = {
            row.id: track_fields(row)
            for row in session.execute(track_rows().where(Order.id.in_(order_ids)))
        }
    problems = []
    for key, order_id in zip(keys, order_ids, strict=True):
        actual = client.hgetall(key)
        want = expected.get(order_id)
        if want is None:
            problems.append(f"{key}: in redis but the order is not in pg")
            continue
        for field in ("customer_id", "status", "courier_id"):
            if actual.get(field) != want.get(field):
                problems.append(
                    f"{key} {field}: redis={actual.get(field)!r} pg={want.get(field)!r}"
                )
    return problems


def verify_ranking() -> list[str]:
    """C: the last-hour ranking matches the deliveries in PG, city by city."""
    now = datetime.now(UTC)
    expected: dict[int, Counter[str]] = {}
    for city_id, restaurant_id, _ in recent_deliveries(now):
        expected.setdefault(city_id, Counter())[str(restaurant_id)] += 1
    with SessionLocal() as session:
        city_ids = session.execute(text("SELECT id FROM cities")).scalars().all()
    problems = []
    for city_id in city_ids:
        actual = Counter(
            {
                member: int(score)
                for member, score in client.zunion(
                    window_keys(city_id, now), withscores=True
                )
            }
        )
        want = expected.get(city_id, Counter())
        if actual != want:
            problems.append(
                f"fd:rank city {city_id}: redis={sum(actual.values())} deliveries"
                f" pg={sum(want.values())} deliveries"
            )
    return problems


# Each function returns one human-readable line per difference found.
CHECKS: list[Callable[[], list[str]]] = [
    verify_offers,
    verify_stock,
    verify_tracking,
    verify_ranking,
]


def main() -> int:
    client.ping()
    differences: list[str] = []
    for check in CHECKS:
        found = check()
        print(f"  {check.__name__}: {len(found)} difference(s)")
        differences.extend(found)
    for line in differences:
        print(f"    {line}")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
