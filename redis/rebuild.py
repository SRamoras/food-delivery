"""Rebuilds every derived Redis key from PostgreSQL (and MongoDB). Safe to re-run.

Run after FLUSHALL, a Redis restore or the seed:
    uv run python redis/rebuild.py
Ephemeral keys are not rebuilt on purpose: courier positions and presence
(fd:couriers:geo, fd:courier:{id}:online) come back with the next position each
courier sends.
"""

from collections.abc import Callable

from app.db.redis import client


def rebuild_offers() -> int:
    """A: fd:offer:{offer_id} for offers still pending in PG, with the remaining TTL."""
    return 0


def rebuild_stock() -> int:
    """B: fd:stock:{item_id}:{date} from today's daily stock rows in PG."""
    return 0


def rebuild_tracking() -> int:
    """C: fd:order:{id}:track for orders that are not finished yet."""
    return 0


def rebuild_ranking() -> int:
    """C: fd:rank:{city_id}:{minute} buckets from the last hour of deliveries in PG."""
    return 0


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
