"""Courier presence and positions (F7): Redis for the live map, MongoDB for the trail."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.db import mongo, redis
from app.db.postgres import SessionLocal
from app.errors import Conflict, NotFound
from app.models.couriers import Courier

GEO_KEY = "fd:couriers:geo"
# 30 s: the brief's rule for "offline". The app sends a position every few seconds,
# so a missing key means the courier stopped sending.
ONLINE_TTL_SECONDS = 30


def online_key(courier_id: int) -> str:
    return f"fd:courier:{courier_id}:online"


def go_online(courier_id: int, lng: float, lat: float) -> None:
    """Put an active courier on the map and start the 30 s online window.

    Only this endpoint reads PostgreSQL: unknown → 404, blocked → 409. /position
    only works while online, so a courier must pass this check to appear on the map.
    """
    with SessionLocal() as session:
        status = session.execute(
            select(Courier.status).where(Courier.id == courier_id)
        ).scalar_one_or_none()
    if status is None:
        raise NotFound("courier not found")
    if status == "blocked":
        raise Conflict("courier is blocked")

    _store_position(courier_id, lng, lat, must_be_online=False)


def send_position(courier_id: int, lng: float, lat: float) -> None:
    """Move an online courier and refresh their online key.

    No PostgreSQL read: positions arrive every few seconds from every courier, and
    the blocked check already ran in go_online. Offline (key expired or /offline) → 409.
    """
    if not _store_position(courier_id, lng, lat, must_be_online=True):
        raise Conflict("courier is offline; call /online first")


def go_offline(courier_id: int) -> None:
    """Take the courier off the map. Idempotent: going offline twice is not an error."""
    # MULTI/EXEC: both commands or neither, so the map and the online key never disagree.
    pipe = redis.client.pipeline(transaction=True)
    pipe.zrem(GEO_KEY, str(courier_id))  # a GEO set is a sorted set: ZREM removes it
    pipe.delete(online_key(courier_id))
    pipe.execute()


def _store_position(
    courier_id: int, lng: float, lat: float, *, must_be_online: bool
) -> bool:
    """Run the Lua script, then append the position to the Mongo trail.

    Redis first: the script decides whether the courier is online, and an offline
    courier's position must not enter the trail. If the Mongo insert then fails, the
    request returns 500 and the live position is still right; only one trail point
    is missing.
    """
    stored = redis.courier_position(
        keys=[GEO_KEY, online_key(courier_id)],
        args=[lng, lat, courier_id, ONLINE_TTL_SECONDS, "1" if must_be_online else "0"],
    )
    if not stored:
        return False

    mongo.db.courier_positions.insert_one(
        {
            "courier_id": courier_id,
            # GeoJSON order is [longitude, latitude].
            "location": {"type": "Point", "coordinates": [lng, lat]},
            # BSON date, so the 7-day TTL index can expire it.
            "recorded_at": datetime.now(UTC),
            # TODO(C-4): add "order_id" when the courier has an active delivery.
        }
    )
    return True
