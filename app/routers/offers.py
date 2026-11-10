"""Restaurant decisions and delivery offers: accept, reject, reoffer (F3)."""

from fastapi import APIRouter

from app.db.postgres import SessionLocal
from app.schemas.offers import OfferedOut, RejectIn, SentOfferOut
from app.schemas.orders import StatusOut
from app.services import offers as service
from app.services.orders import StatusChange
from app.services.side_effects import after_status_change

router = APIRouter(tags=["offers"])


def _offered_out(offered: service.Offered, *, status_changed: bool) -> OfferedOut:
    """Redis writes after the commit (tracking, offer keys), then the response body."""
    if status_changed:
        after_status_change(StatusChange(offered.order))
    service.write_offer_keys(offered)
    return OfferedOut(
        id=offered.order.id,
        status=offered.order.status,
        offers=[
            SentOfferOut(offer_id=o.offer_id, courier_id=o.courier_id)
            for o in offered.offers
        ],
    )


@router.post(
    "/restaurants/{restaurant_id}/orders/{order_id}/accept", response_model=OfferedOut
)
def accept_order(restaurant_id: int, order_id: int) -> OfferedOut:
    """Restaurant accepts a placed order (kitchen full → 409) and offers it to nearby couriers."""
    with SessionLocal() as session, session.begin():
        offered = service.accept_order(session, restaurant_id, order_id)
    return _offered_out(offered, status_changed=True)


@router.post(
    "/restaurants/{restaurant_id}/orders/{order_id}/reject", response_model=StatusOut
)
def reject_order(
    restaurant_id: int, order_id: int, body: RejectIn | None = None
) -> StatusOut:
    """Restaurant rejects a placed order: stock back and refund if paid online."""
    reason = body.reason if body else None
    with SessionLocal() as session, session.begin():
        change = service.reject_order(session, restaurant_id, order_id, reason)
    after_status_change(change)
    return StatusOut(id=change.order.id, status=change.order.status)


@router.post(
    "/restaurants/{restaurant_id}/orders/{order_id}/reoffer", response_model=OfferedOut
)
def restaurant_reoffer(restaurant_id: int, order_id: int) -> OfferedOut:
    """Restaurant offers its accepted order, still without courier, to the next couriers."""
    with SessionLocal() as session, session.begin():
        offered = service.reoffer_order(session, order_id, "restaurant", restaurant_id)
    return _offered_out(offered, status_changed=False)


@router.post("/backoffice/orders/{order_id}/reoffer", response_model=OfferedOut)
def backoffice_reoffer(order_id: int) -> OfferedOut:
    """Back office offers any accepted order, still without courier, to the next couriers."""
    with SessionLocal() as session, session.begin():
        offered = service.reoffer_order(session, order_id, "backoffice", None)
    return _offered_out(offered, status_changed=False)
