"""Courier position trail seed: positions of the last 7 days, built from PG deliveries.

Runs after the couriers seed (see scripts/seed.sh). Reads PostgreSQL as fd_readonly
and writes MongoDB as fd_app. Each delivery of the last 7 days becomes a trail: the
courier riding to the restaurant, then to the customer with the order_id, one point
per minute. Dates are relative to now, or the 7-day TTL index would delete them.
"""

import math
import random
import time
from datetime import UTC, datetime, timedelta

import psycopg
from pymongo import MongoClient

from app.config import settings

random.seed(42)

TRAIL_DAYS = 7  # same as the TTL index on recorded_at
STEP = timedelta(seconds=60)  # one point per minute (the app sends more often)
BATCH = 20_000
MIN_DOCS = 50_000  # the brief's minimum


def jitter(lat: float, lng: float, metres: float) -> tuple[float, float]:
    """A point up to `metres` away in a random direction (GPS noise, start position)."""
    angle = random.uniform(0, 2 * math.pi)
    d = random.uniform(0, metres) / 111_320
    return lat + d * math.sin(angle), lng + d * math.cos(angle) / math.cos(
        math.radians(lat)
    )


def leg(
    start: tuple[float, float],
    end: tuple[float, float],
    t0: datetime,
    t1: datetime,
    courier_id: int,
    order_id: int | None,
    since: datetime,
):
    """Points every STEP on the straight line start → end between t0 and t1."""
    total = (t1 - t0).total_seconds()
    t = t0
    while t <= t1:
        if t >= since:
            f = (t - t0).total_seconds() / total if total else 1.0
            lat, lng = jitter(
                start[0] + (end[0] - start[0]) * f,
                start[1] + (end[1] - start[1]) * f,
                15,
            )
            doc = {
                "courier_id": courier_id,
                # GeoJSON order is [longitude, latitude]; floats, so BSON double.
                "location": {"type": "Point", "coordinates": [lng, lat]},
                "recorded_at": t,
            }
            if order_id is not None:
                doc["order_id"] = order_id
            yield doc
        t += STEP


def main() -> None:
    """Build every trail and insert it in batches. Skipped if positions already exist."""
    started = time.monotonic()
    client = MongoClient(settings.mongo_url)
    positions = client.get_default_database()["courier_positions"]
    if positions.estimated_document_count():
        print("courier positions already seeded, skipped")
        return

    url = (settings.readonly_database_url or settings.database_url).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    now = datetime.now(UTC)
    since = now - timedelta(days=TRAIL_DAYS)
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        # Deliveries that moved in the window, with the restaurant and the address.
        cur.execute(
            """
            SELECT d.courier_id, d.order_id, d.accepted_at, d.picked_up_at,
                   d.delivered_at, r.lat, r.lng, o.delivery_lat, o.delivery_lng
              FROM deliveries d
              JOIN orders o ON o.id = d.order_id
              JOIN restaurants r ON r.id = o.restaurant_id
             WHERE coalesce(d.delivered_at, now()) >= %s
             ORDER BY d.accepted_at
            """,
            (since,),
        )
        rows = cur.fetchall()

    batch, total = [], 0
    for courier, order, accepted, picked, delivered, rlat, rlng, dlat, dlng in rows:
        rest = (float(rlat), float(rlng))
        home = (float(dlat), float(dlng))
        # Leg 1: from somewhere up to 1.5 km away to the restaurant, no order yet
        # (the courier is not carrying it). Ends at pickup, or now if not picked up.
        start = jitter(*rest, 1500)
        docs = list(leg(start, rest, accepted, picked or now, courier, None, since))
        # Leg 2: carrying the order to the customer, with order_id.
        if picked:
            docs += leg(rest, home, picked, delivered or now, courier, order, since)
        batch += docs
        if len(batch) >= BATCH:
            positions.insert_many(batch, ordered=False)
            total += len(batch)
            batch = []
    if batch:
        positions.insert_many(batch, ordered=False)
        total += len(batch)
    client.close()

    note = "" if total >= MIN_DOCS else f" (below the {MIN_DOCS} the brief asks for)"
    print(
        f"  positions={total} from {len(rows)} deliveries"
        f" in {time.monotonic() - started:.0f} s{note}"
    )


if __name__ == "__main__":
    main()
