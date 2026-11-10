"""Kitchen capacity (rule 4): a restaurant never has more active orders than it can cook."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import Conflict, NotFound
from app.models.orders import ACTIVE_KITCHEN_STATUSES, Order
from app.models.restaurants import Restaurant


def ensure_kitchen_room(session: Session, restaurant_id: int) -> None:
    """Refuse (409) when the restaurant already has kitchen_capacity active orders.

    A calls it inside F3 accept, in the same transaction, before moving the order to
    `accepted`. Active = accepted, preparing or ready.

    Without a lock this is a write skew: two accepts for different orders of the same
    restaurant both count "capacity - 1", both pass, and each updates a different
    order row, so nothing conflicts. Locking the restaurant row (FOR UPDATE) makes
    every accept for that restaurant wait for the previous one to commit; the next
    one then counts the order just accepted. The lock is held until the commit.

    Lock order: the caller locks the order first (lock_order), then this locks the
    restaurant. No flow locks them the other way round, so there is no deadlock.
    """
    capacity = session.execute(
        select(Restaurant.kitchen_capacity)
        .where(Restaurant.id == restaurant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if capacity is None:
        raise NotFound("restaurant not found")
    # Served by the partial index ix_orders_restaurant_active (active orders only).
    active = session.execute(
        select(func.count())
        .select_from(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status.in_(ACTIVE_KITCHEN_STATUSES),
        )
    ).scalar_one()
    if active >= capacity:
        raise Conflict("kitchen is full")
