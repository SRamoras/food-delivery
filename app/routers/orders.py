"""Order endpoints: place (F2), kitchen steps, cancel and courier steps (F5)."""

from typing import Literal

from fastapi import APIRouter

from app.config import settings
from app.db.postgres import SessionLocal
from app.errors import NotFound
from app.schemas.orders import CancelIn, OrderOut, PlaceOrderIn, StatusOut
from app.services import orders as order_service
from app.services.side_effects import after_order_placed, after_status_change

router = APIRouter(tags=["orders"])


# `def`, not `async def`: FastAPI runs it in its thread pool, so simultaneous orders
# reach PostgreSQL in parallel (what the last-portions test needs).
@router.post(
    "/customers/{customer_id}/orders", status_code=201, response_model=OrderOut
)
def place_order(
    customer_id: int, body: PlaceOrderIn, mode: Literal["real", "naive"] = "real"
) -> OrderOut:
    """Place an order: restaurant, items, minimum and daily stock checked in one transaction."""
    naive = mode == "naive"
    # With the switch off, the naive path does not exist (404), so it cannot be used
    # by accident outside the concurrency test and the demo.
    if naive and not settings.enable_naive_mode:
        raise NotFound("naive mode is disabled")
    # Commits at the end of the block; a 404/409 raised inside rolls everything back.
    with SessionLocal() as session, session.begin():
        placed = order_service.place_order(session, customer_id, body, naive=naive)
    # Outside the `with`: Redis is written only after PostgreSQL has committed.
    after_order_placed(placed)
    return OrderOut.model_validate(placed.order, from_attributes=True)


def _status_out(change: order_service.StatusChange) -> StatusOut:
    """Redis copies after the commit, then the response body."""
    after_status_change(change)
    return StatusOut(id=change.order.id, status=change.order.status)


@router.post(
    "/restaurants/{restaurant_id}/orders/{order_id}/preparing", response_model=StatusOut
)
def mark_preparing(restaurant_id: int, order_id: int) -> StatusOut:
    """Restaurant starts preparing an accepted order."""
    with SessionLocal() as session, session.begin():
        change = order_service.kitchen_step(
            session, restaurant_id, order_id, "preparing"
        )
    return _status_out(change)


@router.post(
    "/restaurants/{restaurant_id}/orders/{order_id}/ready", response_model=StatusOut
)
def mark_ready(restaurant_id: int, order_id: int) -> StatusOut:
    """Restaurant marks an order in preparation as ready for pickup."""
    with SessionLocal() as session, session.begin():
        change = order_service.kitchen_step(session, restaurant_id, order_id, "ready")
    return _status_out(change)


@router.post(
    "/customers/{customer_id}/orders/{order_id}/cancel", response_model=StatusOut
)
def customer_cancel(customer_id: int, order_id: int, body: CancelIn) -> StatusOut:
    """Customer cancels their order before pickup, with a reason."""
    with SessionLocal() as session, session.begin():
        change = order_service.cancel_order(
            session, order_id, "customer", customer_id, body.reason
        )
    return _status_out(change)


@router.post(
    "/restaurants/{restaurant_id}/orders/{order_id}/cancel", response_model=StatusOut
)
def restaurant_cancel(restaurant_id: int, order_id: int, body: CancelIn) -> StatusOut:
    """Restaurant cancels one of its orders before pickup, with a reason."""
    with SessionLocal() as session, session.begin():
        change = order_service.cancel_order(
            session, order_id, "restaurant", restaurant_id, body.reason
        )
    return _status_out(change)


@router.post("/backoffice/orders/{order_id}/cancel", response_model=StatusOut)
def backoffice_cancel(order_id: int, body: CancelIn) -> StatusOut:
    """Back office cancels any order before pickup, with a reason."""
    with SessionLocal() as session, session.begin():
        change = order_service.cancel_order(
            session, order_id, "backoffice", None, body.reason
        )
    return _status_out(change)


@router.post(
    "/couriers/{courier_id}/deliveries/{order_id}/picked-up", response_model=StatusOut
)
def mark_picked_up(courier_id: int, order_id: int) -> StatusOut:
    """Courier picks up a ready order from the restaurant."""
    with SessionLocal() as session, session.begin():
        change = order_service.courier_step(session, courier_id, order_id, "picked_up")
    return _status_out(change)


@router.post(
    "/couriers/{courier_id}/deliveries/{order_id}/delivered", response_model=StatusOut
)
def mark_delivered(courier_id: int, order_id: int) -> StatusOut:
    """Courier hands a picked-up order to the customer."""
    with SessionLocal() as session, session.begin():
        change = order_service.courier_step(session, courier_id, order_id, "delivered")
    return _status_out(change)
