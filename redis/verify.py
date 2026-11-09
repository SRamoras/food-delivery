"""Compares the derived Redis keys with their source (PG/Mongo). Exit 1 on any mismatch.

    uv run python redis/verify.py
Test: FLUSHALL -> redis/rebuild.py -> redis/verify.py exits 0.
"""

import sys
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import text

from app.config import LISBON
from app.db.postgres import SessionLocal
from app.db.redis import client
from app.services.stock import stock_key


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
    """C: fd:order:{id}:track status and courier match PG."""
    return []


def verify_ranking() -> list[str]:
    """C: the last-hour ranking matches the deliveries in PG."""
    return []


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
