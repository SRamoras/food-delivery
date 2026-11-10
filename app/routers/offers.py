"""Delivery offers: restaurant accept, reject, reoffer (F3) and courier accept, decline (F4)."""

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app.config import settings
from app.db.postgres import SessionLocal
from app.errors import NotFound
from app.schemas.offers import OfferAnswerOut, OfferedOut, RejectIn, SentOfferOut
from app.schemas.orders import StatusOut
from app.services import courier_offers
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


def _answer_offer(
    courier_id: int,
    offer_id: int,
    answer: Callable[[Session, int, int], courier_offers.OfferAnswer],
) -> OfferAnswerOut:
    """Run accept or decline in one transaction, then the Redis writes."""
    try:
        with SessionLocal() as session, session.begin():
            result = answer(session, courier_id, offer_id)
    except courier_offers.OfferExpired:
        # The failed transaction rolled back; write `expired` in a new one, then
        # still answer 409.
        with SessionLocal() as session, session.begin():
            courier_offers.mark_expired(session, offer_id)
        courier_offers.delete_offer_keys([offer_id])
        raise
    courier_offers.delete_offer_keys(result.closed_offer_ids)
    if result.order is not None:
        # The status does not change; the tracking hash gets the courier.
        after_status_change(StatusChange(result.order, courier_id=courier_id))
    offer = result.offer
    return OfferAnswerOut(
        offer_id=offer.id,
        order_id=offer.order_id,
        courier_id=offer.courier_id,
        outcome=offer.outcome,
    )


@router.post(
    "/couriers/{courier_id}/offers/{offer_id}/accept", response_model=OfferAnswerOut
)
def accept_offer(
    courier_id: int, offer_id: int, mode: Literal["real", "naive"] = "real"
) -> OfferAnswerOut:
    """Courier accepts an offer: only the first valid accept wins, the others get 409."""
    if mode == "naive":
        # With the switch off, the naive path does not exist (404), so it cannot be
        # used by accident outside the concurrency test and the demo.
        if not settings.enable_naive_mode:
            raise NotFound("naive mode is disabled")
        return _answer_offer(courier_id, offer_id, courier_offers.accept_offer_naive)
    return _answer_offer(courier_id, offer_id, courier_offers.accept_offer)


@router.post(
    "/couriers/{courier_id}/offers/{offer_id}/reject", response_model=OfferAnswerOut
)
def decline_offer(courier_id: int, offer_id: int) -> OfferAnswerOut:
    """Courier declines a pending offer."""
    return _answer_offer(courier_id, offer_id, courier_offers.decline_offer)
