"""Order status machine shared by every flow that changes an order (F2, F3, F5)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, NotFound
from app.models.orders import Order, OrderStatusHistory

# From each status, the statuses an order may move to (None = the order does not
# exist yet, so F2 goes through the same check). Cancel is allowed from every status
# before picked_up; the final statuses lead nowhere.
ALLOWED: dict[str | None, frozenset[str]] = {
    None: frozenset({"placed"}),
    "placed": frozenset({"accepted", "rejected", "cancelled"}),
    "accepted": frozenset({"preparing", "cancelled"}),
    "preparing": frozenset({"ready", "cancelled"}),
    "ready": frozenset({"picked_up", "cancelled"}),
    "picked_up": frozenset({"delivered"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
    "rejected": frozenset(),
}

# For each target status, who may move an order into it. Kept apart from ALLOWED
# because "does this move exist?" and "may this actor make it?" are different rules.
ACTORS_FOR: dict[str, frozenset[str]] = {
    "placed": frozenset({"customer"}),
    "accepted": frozenset({"restaurant"}),
    "rejected": frozenset({"restaurant"}),
    "preparing": frozenset({"restaurant"}),
    "ready": frozenset({"restaurant"}),
    "picked_up": frozenset({"courier"}),
    "delivered": frozenset({"courier"}),
    "cancelled": frozenset({"customer", "restaurant", "backoffice"}),
}


def check_transition(old: str | None, new: str, actor_type: str) -> None:
    """Check both tables: the move must exist (ALLOWED) and the actor may make it.

    Raises Conflict, which becomes a 409: an invalid transition is a business rule
    refusal, never a 5xx.
    """
    # .get(): an unknown old status has no allowed moves, so it is refused too.
    if new not in ALLOWED.get(old, frozenset()):
        raise Conflict(f"cannot change order status from {old} to {new}")
    if actor_type not in ACTORS_FOR[new]:
        raise Conflict(f"a {actor_type} cannot set an order to {new}")


def lock_order(session: Session, order_id: int) -> Order:
    """Read the order and lock its row until the transaction ends (SELECT ... FOR UPDATE).

    Two requests on the same order cannot overlap: the second waits for the first
    to commit, then reads the new status and is checked against it. Missing → 404.
    """
    order = session.execute(
        select(Order).where(Order.id == order_id).with_for_update()
    ).scalar_one_or_none()
    if order is None:
        raise NotFound("order not found")
    return order


def record_status(
    session: Session,
    order_id: int,
    old: str | None,
    new: str,
    actor_type: str,
    actor_id: int | None,
) -> None:
    """Add one history row (old, new, who) to the caller's transaction.

    Same transaction as the status change: both are saved, or neither is.
    """
    session.add(
        OrderStatusHistory(
            order_id=order_id,
            old_status=old,
            new_status=new,
            actor_type=actor_type,
            actor_id=actor_id,
        )
    )


def change_status(
    session: Session,
    order: Order,
    new: str,
    actor_type: str,
    actor_id: int | None,
    *,
    reason: str | None = None,
) -> None:
    """Check, change the status and write the history, all in one go.

    The order must already be locked with lock_order(). Used by B (F5, cancel) and
    A (F3 accept/reject). A cancel needs a reason and records who cancelled; a reject
    may give a reason. PostgreSQL's CHECK limits the reason to the fixed list.
    """
    old = order.status
    # Check first: a refused move changes nothing and writes no history.
    check_transition(old, new, actor_type)
    if new == "cancelled":
        # 409, not 422: a missing reason is a business rule. The router's Pydantic
        # schema already requires it, so this is only defence in depth.
        if not reason:
            raise Conflict("a cancel reason is required")
        order.cancel_reason = reason
        # Also in the history; kept on the order so the report export needs no join.
        order.cancelled_by = actor_type
    elif new == "rejected" and reason:
        order.cancel_reason = reason
    order.status = new
    record_status(session, order.id, old, new, actor_type, actor_id)
