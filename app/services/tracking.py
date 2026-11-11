"""F6 tracking: an order's status and courier position, answered from Redis."""

from datetime import datetime

from sqlalchemy import Row, Select, func, select

from app.config import LISBON
from app.db import redis
from app.db.postgres import SessionLocal
from app.errors import NotFound
from app.models.offers import Delivery
from app.models.orders import Order, OrderStatusHistory
from app.schemas.tracking import CourierPosition, OrderTracking

# One day is far longer than any delivery, and finished orders then leave memory alone.
TRACK_TTL_SECONDS = 86400
COURIERS_GEO_KEY = "fd:couriers:geo"


def track_key(order_id: int) -> str:
    return f"fd:order:{order_id}:track"


def track_rows() -> Select:
    """What the tracking hash holds, read from PG: one row per order.

    Shared by the cache miss, redis/rebuild.py and redis/verify.py, so all three
    agree on what the hash should contain.
    """
    last_change = (
        select(func.max(OrderStatusHistory.changed_at))
        .where(OrderStatusHistory.order_id == Order.id)
        .scalar_subquery()
    )
    return select(
        Order.id,
        Order.customer_id,
        Order.status,
        Delivery.courier_id,
        func.coalesce(last_change, Order.created_at).label("updated_at"),
    ).outerjoin(Delivery, Delivery.order_id == Order.id)


def track_fields(row: Row) -> dict[str, str]:
    """A track_rows() row as the hash fields (Redis stores strings)."""
    fields = {
        "customer_id": str(row.customer_id),
        "status": row.status,
        "updated_at": row.updated_at.isoformat(),
    }
    if row.courier_id is not None:
        fields["courier_id"] = str(row.courier_id)
    return fields


def update_tracking(
    order_id: int, customer_id: int, status: str, courier_id: int | None
) -> None:
    """Write an order's tracking hash. Call it only after the PG transaction commits.

    Before the commit, a rollback would leave Redis showing a status that never
    happened. courier_id None keeps the courier already stored, so a caller that does
    not know it cannot erase it. HSET and EXPIRE run in one MULTI, so a key never
    exists without its TTL.
    """
    fields: dict[str, str | int] = {
        "customer_id": customer_id,
        "status": status,
        "updated_at": datetime.now(LISBON).isoformat(),
    }
    if courier_id is not None:
        fields["courier_id"] = courier_id

    key = track_key(order_id)
    pipe = redis.client.pipeline(transaction=True)
    pipe.hset(key, mapping=fields)
    pipe.expire(key, TRACK_TTL_SECONDS)
    pipe.execute()


def _fill_from_postgres(order_id: int) -> dict[str, str] | None:
    """On a cache miss, read the order once from PG and store it. None if it does not exist.

    The courier comes from A's deliveries table (outer join: no row until a courier
    accepts).
    """
    with SessionLocal() as session, session.begin():
        row = session.execute(track_rows().where(Order.id == order_id)).one_or_none()
    if row is None:
        return None

    fields = track_fields(row)
    flat = [part for pair in fields.items() for part in pair]
    redis.fill_tracking(keys=[track_key(order_id)], args=[TRACK_TTL_SECONDS, *flat])
    return fields


def get_tracking(customer_id: int, order_id: int) -> OrderTracking:
    """Return an order's status and its courier's last known position.

    A repeated request never touches PostgreSQL: ownership is checked against the
    customer_id stored in the hash, not with a SELECT.

    Raises:
        NotFound: the order does not exist or belongs to another customer.
    """
    track = redis.client.hgetall(track_key(order_id)) or _fill_from_postgres(order_id)
    # Same answer for "not yours" and "does not exist", so ids cannot be probed.
    if track is None or int(track["customer_id"]) != customer_id:
        raise NotFound("Order not found")

    courier_id = int(track["courier_id"]) if "courier_id" in track else None
    position = None
    if courier_id is not None:
        # GEOPOS returns [None] when the courier has left the geo set (offline).
        point = redis.client.geopos(COURIERS_GEO_KEY, courier_id)[0]
        if point is not None:
            position = CourierPosition(lng=point[0], lat=point[1])

    return OrderTracking(
        order_id=order_id,
        status=track["status"],
        courier_id=courier_id,
        courier_position=position,
        updated_at=datetime.fromisoformat(track["updated_at"]),
    )
