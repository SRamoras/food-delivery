"""Writes to Redis that follow a PostgreSQL commit. They never undo or fail the request."""

import logging
from datetime import datetime

from app.config import LISBON
from app.services.courier_offers import delete_offer_keys
from app.services.orders import PlacedOrder, StatusChange
from app.services.ranking import record_delivery
from app.services.stock import write_stock_copies
from app.services.tracking import update_tracking

log = logging.getLogger(__name__)


def after_order_placed(placed: PlacedOrder) -> None:
    """Copy the new stock to Redis. PostgreSQL has already committed the order.

    A Redis failure here must not become a 500: the order exists and the customer was
    charged. The key is derived data, so redis/verify.py finds the gap and
    redis/rebuild.py fixes it.
    """
    order = placed.order
    try:
        write_stock_copies(placed.stock_after, placed.stock_date)
    except Exception:
        log.exception("fd:stock update failed for order %s", order.id)
    _track(order.id, order.customer_id, order.status, None)


def after_status_change(change: StatusChange) -> None:
    """Update tracking, the ranking and any stock a cancel gave back. PG has committed.

    Only today's stock key: yesterday's stock is never read again.
    """
    order = change.order
    _track(order.id, order.customer_id, order.status, change.courier_id)
    # A cancel withdrew these offers in PG; their keys would otherwise live up to 45 s.
    delete_offer_keys(change.withdrawn_offer_ids)
    if order.status == "delivered" and change.city_id is not None:
        # Derived like the others: a failure is logged and rebuild.py fixes it.
        try:
            record_delivery(change.city_id, order.restaurant_id)
        except Exception:
            log.exception("fd:rank update failed for order %s", order.id)
    if not change.stock_after or change.stock_date != datetime.now(LISBON).date():
        return
    try:
        write_stock_copies(change.stock_after, change.stock_date)
    except Exception:
        log.exception("fd:stock update failed for order %s", order.id)


def _track(
    order_id: int, customer_id: int, status: str, courier_id: int | None
) -> None:
    """C's tracking hash. A failure is only logged: F6 refills it from PG on a miss."""
    try:
        update_tracking(order_id, customer_id, status, courier_id)
    except Exception:
        log.exception("fd:order track update failed for order %s", order_id)
