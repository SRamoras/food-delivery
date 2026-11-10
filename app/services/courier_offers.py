"""A courier's answer to a delivery offer (F4): accept (rules 1 and 3) or decline."""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import redis
from app.errors import Conflict, NotFound
from app.models.couriers import VEHICLE_CAPACITY, Courier
from app.models.offers import OFFER_TTL_SECONDS, Delivery, DeliveryOffer
from app.models.orders import ACTIVE_KITCHEN_STATUSES, Order
from app.services.offers import offer_key
from app.services.order_status import lock_order

log = logging.getLogger(__name__)

# Constraints that back rule 1. A violation of one of them is "someone else won"
# (409); any other IntegrityError is a bug and stays a 500.
RULE_1_CONSTRAINTS = {
    "uq_deliveries_order_id",
    "uq_delivery_offers_one_accepted_per_order",
}


class OfferExpired(Conflict):
    """The offer is still `pending` but its 45 s are over.

    Raised so the request transaction rolls back; the router then marks the offer
    `expired` in its own short transaction (lazy expiry, no worker).
    """


@dataclass
class OfferAnswer:
    """What accept and decline return, and the Redis keys to delete after the commit."""

    offer: DeliveryOffer
    order: Order | None = None
    # Every fd:offer key of the order that is no longer pending (accept: all of them).
    closed_offer_ids: list[int] = field(default_factory=list)


def count_active_deliveries(session: Session, courier_id: int) -> int:
    """Deliveries the courier still has to finish: not delivered, order not cancelled.

    Same definition as the room filter in F3 (_offer_to_nearby). Uses the partial
    index ix_deliveries_courier_active (delivered_at IS NULL).
    """
    return session.execute(
        text("""
            SELECT count(*)
              FROM deliveries d
              JOIN orders o ON o.id = d.order_id
             WHERE d.courier_id = :c
               AND d.delivered_at IS NULL
               AND o.status <> 'cancelled'
        """),
        {"c": courier_id},
    ).scalar_one()


def _lock_offer(
    session: Session, courier_id: int, offer_id: int
) -> tuple[DeliveryOffer, Order]:
    """Lock the order, then the offer, and check the offer is this courier's and valid.

    Lock order is the same as cancel and reoffer (order first, then its offers), so
    they wait for each other instead of deadlocking. The offer is read once without a
    lock only to learn its order_id, which never changes.
    """
    order_id = session.execute(
        select(DeliveryOffer.order_id).where(
            DeliveryOffer.id == offer_id, DeliveryOffer.courier_id == courier_id
        )
    ).scalar_one_or_none()
    # Someone else's offer → 404, as if it did not exist.
    if order_id is None:
        raise NotFound("offer not found")

    order = lock_order(session, order_id)
    # now() is the transaction start, the same clock that filled sent_at.
    offer, fresh = session.execute(
        select(
            DeliveryOffer,
            DeliveryOffer.sent_at > func.now() - timedelta(seconds=OFFER_TTL_SECONDS),
        )
        .where(DeliveryOffer.id == offer_id)
        .with_for_update(of=DeliveryOffer)
    ).one()
    if offer.outcome != "pending":
        raise Conflict(f"offer is {offer.outcome}")
    if not fresh:
        raise OfferExpired("offer has expired")
    return offer, order


def accept_offer(session: Session, courier_id: int, offer_id: int) -> OfferAnswer:
    """Courier accepts an offer: exactly one courier per order (rule 1), vehicle limit (rule 3).

    Rule 1: the order row lock (FOR UPDATE) makes simultaneous accepts for the same
    order run one at a time. The first inserts the delivery and withdraws the other
    offers; the next ones then see their offer `withdrawn` → 409. UNIQUE (order_id)
    on deliveries is the last guarantee if this logic ever has a bug.
    Rule 3: the courier row is locked before counting their active deliveries, so two
    accepts by the same courier (different orders) cannot both see a free slot.
    """
    offer, order = _lock_offer(session, courier_id, offer_id)

    # Withdrawn offers already cover a cancelled order or a taken one; this is the
    # direct check, in case an offer was left pending by mistake.
    if order.status not in ACTIVE_KITCHEN_STATUSES:
        raise Conflict(f"order is {order.status}")
    taken = session.execute(
        select(Delivery.id).where(Delivery.order_id == order.id)
    ).first()
    if taken is not None:
        raise Conflict("order already has a courier")

    courier = session.execute(
        select(Courier).where(Courier.id == courier_id).with_for_update()
    ).scalar_one()
    if courier.status != "active":
        raise Conflict("courier is blocked")
    if (
        count_active_deliveries(session, courier_id)
        >= VEHICLE_CAPACITY[courier.vehicle_type]
    ):
        raise Conflict(f"no room left on the {courier.vehicle_type}")

    session.add(Delivery(order_id=order.id, courier_id=courier_id))
    offer.outcome = "accepted"
    try:
        # flush sends the INSERT and UPDATE now, so a unique violation is caught here.
        session.flush()
    except IntegrityError as exc:
        if getattr(exc.orig.diag, "constraint_name", None) in RULE_1_CONSTRAINTS:
            raise Conflict("order already has a courier") from exc
        raise

    withdrawn = session.execute(
        update(DeliveryOffer)
        .where(
            DeliveryOffer.order_id == order.id,
            DeliveryOffer.id != offer.id,
            DeliveryOffer.outcome == "pending",
        )
        .values(outcome="withdrawn")
        .returning(DeliveryOffer.id)
    ).scalars()
    return OfferAnswer(offer, order, [offer.id, *withdrawn])


def decline_offer(session: Session, courier_id: int, offer_id: int) -> OfferAnswer:
    """Courier declines a pending, still valid offer → outcome `rejected`.

    Same locks as accept (order, then offer), so a decline and an accept of the
    same offer, or a cancel of its order, run one after the other.
    """
    offer, _ = _lock_offer(session, courier_id, offer_id)
    offer.outcome = "rejected"
    return OfferAnswer(offer, closed_offer_ids=[offer.id])


def mark_expired(session: Session, offer_id: int) -> None:
    """Lazy expiry: write `expired` on an offer found too old by accept or decline.

    Conditional UPDATE, so it changes nothing if the offer stopped being pending in
    the meantime (e.g. the order was cancelled and the offer withdrawn).
    """
    session.execute(
        update(DeliveryOffer)
        .where(
            DeliveryOffer.id == offer_id,
            DeliveryOffer.outcome == "pending",
            DeliveryOffer.sent_at <= func.now() - timedelta(seconds=OFFER_TTL_SECONDS),
        )
        .values(outcome="expired")
    )


def delete_offer_keys(offer_ids: list[int]) -> None:
    """Delete fd:offer keys of offers that are no longer pending. After the PG commit.

    The keys are ephemeral (EX 45) and F4 never trusts them, so a failure is only
    logged: they disappear on their own within 45 s.
    """
    if not offer_ids:
        return
    try:
        redis.client.delete(*(offer_key(i) for i in offer_ids))
    except Exception:
        log.exception("fd:offer delete failed for offers %s", offer_ids)
