"""Restaurant decisions on a new order (F3): accept and offer it to couriers, reject, reoffer."""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.db import redis
from app.errors import Conflict
from app.models.couriers import VEHICLE_CAPACITY
from app.models.offers import OFFER_TTL_SECONDS, Delivery, DeliveryOffer
from app.models.orders import ACTIVE_KITCHEN_STATUSES, Order
from app.models.restaurants import Restaurant
from app.services.couriers import GEO_KEY, online_key
from app.services.order_status import change_status, check_transition, lock_order
from app.services.orders import (
    StatusChange,
    _check_owner,
    check_kitchen_capacity,
    release_and_refund,
)

log = logging.getLogger(__name__)

# The brief: offer to up to 5 couriers within 3 km of the restaurant.
OFFER_RADIUS_KM = 3
MAX_OFFERS = 5


def offer_key(offer_id: int) -> str:
    return f"fd:offer:{offer_id}"


@dataclass
class SentOffer:
    offer_id: int
    courier_id: int


@dataclass
class Offered:
    """What accept and reoffer return: the order and the offers just created."""

    order: Order
    offers: list[SentOffer] = field(default_factory=list)


def accept_order(session: Session, restaurant_id: int, order_id: int) -> Offered:
    """Restaurant accepts its `placed` order (rule 4 checked) and offers it to couriers.

    Locks in a fixed order: the order row (lock_order), then the restaurant row
    (check_kitchen_capacity). Two accepts of the same order: the second waits, sees
    `accepted` and gets 409. Two accepts for the same restaurant: the second counts
    the kitchen only after the first committed, so capacity is never exceeded.
    """
    order = lock_order(session, order_id)
    _check_owner(order, "restaurant", restaurant_id)
    # Transition first: an order that is no longer `placed` gets 409 without
    # taking the restaurant lock, which every accept of that restaurant waits for.
    check_transition(order.status, "accepted", "restaurant")
    check_kitchen_capacity(session, order.restaurant_id)
    change_status(session, order, "accepted", "restaurant", restaurant_id)
    return Offered(order, _offer_to_nearby(session, order))


def reject_order(
    session: Session, restaurant_id: int, order_id: int, reason: str | None
) -> StatusChange:
    """Restaurant rejects its `placed` order: portions back to the stock, refund if paid online.

    The order is locked first, as in every flow, so a reject and a customer cancel
    of the same order run one after the other and only one gives the stock back.
    """
    order = lock_order(session, order_id)
    _check_owner(order, "restaurant", restaurant_id)
    change_status(
        session, order, "rejected", "restaurant", restaurant_id, reason=reason
    )
    stock_after, day = release_and_refund(session, order)
    return StatusChange(order, stock_after, day)


def reoffer_order(
    session: Session, order_id: int, actor_type: str, actor_id: int | None
) -> Offered:
    """Offer an accepted order with no courier yet to the next nearby couriers.

    Offers older than 45 s are marked `expired` here (lazy expiry, no worker). Offers
    still inside their 45 s stay `pending`: they can still be accepted. The order row
    lock makes a reoffer and a courier's accept (F4 locks the order too) run one after
    the other, so an order that just got its courier is not offered again.
    """
    order = lock_order(session, order_id)
    _check_owner(order, actor_type, actor_id)
    if order.status not in ACTIVE_KITCHEN_STATUSES:
        raise Conflict(f"an order in status {order.status} cannot be offered")
    has_courier = session.execute(
        select(Delivery.id).where(Delivery.order_id == order.id)
    ).first()
    if has_courier is not None:
        raise Conflict("order already has a courier")

    # now() is the transaction start time, the same clock that filled sent_at.
    session.execute(
        update(DeliveryOffer)
        .where(
            DeliveryOffer.order_id == order.id,
            DeliveryOffer.outcome == "pending",
            DeliveryOffer.sent_at <= func.now() - timedelta(seconds=OFFER_TTL_SECONDS),
        )
        .values(outcome="expired")
    )
    return Offered(order, _offer_to_nearby(session, order))


def _offer_to_nearby(session: Session, order: Order) -> list[SentOffer]:
    """Create `pending` offers for up to 5 online couriers within 3 km who have room.

    Redis answers "who is near and online"; PostgreSQL answers "who is active, has
    room (rule 3) and was not offered this order yet". This filter by room is only a
    first pass: F4 checks again with the courier row locked, because the courier may
    accept another offer in the meantime. No courier found is not an error: the
    restaurant or the back office can reoffer later.
    """
    rest = session.get(Restaurant, order.restaurant_id)
    # Closest first, so the 5 offers go to the nearest couriers that pass the filters.
    nearby = [
        int(member)
        for member in redis.client.geosearch(
            GEO_KEY,
            longitude=float(rest.lng),
            latitude=float(rest.lat),
            radius=OFFER_RADIUS_KM,
            unit="km",
            sort="ASC",
        )
    ]
    if not nearby:
        return []
    # A GEO member has no TTL, so a courier who stopped sending positions is still
    # on the map; the online key (EX 30) is what says they are online.
    pipe = redis.client.pipeline(transaction=False)
    for courier_id in nearby:
        pipe.exists(online_key(courier_id))
    online = [cid for cid, is_on in zip(nearby, pipe.execute(), strict=True) if is_on]
    if not online:
        return []

    # Active delivery = not delivered yet and its order not cancelled. The
    # deliveries index ix_deliveries_courier_active covers `delivered_at IS NULL`.
    rows = session.execute(
        text("""
            SELECT c.id, c.vehicle_type,
                   (SELECT count(*)
                      FROM deliveries d
                      JOIN orders o ON o.id = d.order_id
                     WHERE d.courier_id = c.id
                       AND d.delivered_at IS NULL
                       AND o.status <> 'cancelled') AS active
              FROM couriers c
             WHERE c.id = ANY(:ids)
               AND c.status = 'active'
               AND NOT EXISTS (SELECT 1 FROM delivery_offers f
                                WHERE f.order_id = :order_id AND f.courier_id = c.id)
        """),
        {"ids": online, "order_id": order.id},
    ).all()
    has_room = {
        row.id for row in rows if row.active < VEHICLE_CAPACITY[row.vehicle_type]
    }
    chosen = [cid for cid in online if cid in has_room][:MAX_OFFERS]

    offers = [DeliveryOffer(order_id=order.id, courier_id=cid) for cid in chosen]
    session.add_all(offers)
    # flush sends the INSERTs (no commit) so each offer gets its id.
    session.flush()
    return [SentOffer(offer.id, offer.courier_id) for offer in offers]


def write_offer_keys(offered: Offered) -> None:
    """Write fd:offer:{id} for each new offer. Call it only after PostgreSQL commits.

    HSET and EXPIRE in one MULTI, so a key never exists without its 45 s TTL. The
    key is ephemeral: F4 decides validity from PostgreSQL (`pending` and sent_at),
    so a Redis failure is only logged and never undoes the accept.
    """
    if not offered.offers:
        return
    try:
        pipe = redis.client.pipeline(transaction=True)
        for offer in offered.offers:
            key = offer_key(offer.offer_id)
            pipe.hset(
                key,
                mapping={
                    "order_id": offered.order.id,
                    "courier_id": offer.courier_id,
                    "restaurant_id": offered.order.restaurant_id,
                },
            )
            pipe.expire(key, OFFER_TTL_SECONDS)
        pipe.execute()
    except Exception:
        log.exception("fd:offer write failed for order %s", offered.order.id)
