"""Writes to Redis that follow a PostgreSQL commit. They never undo or fail the request."""

import logging
from datetime import datetime

from app.config import LISBON
from app.services.orders import PlacedOrder, StatusChange
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
    """Update tracking and copy any stock a cancel gave back. PostgreSQL has committed.

    Only today's stock key: yesterday's stock is never read again. The ranking call
    on `delivered` (C's function) is added when it exists.
    """
    order = change.order
    _track(order.id, order.customer_id, order.status, change.courier_id)
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
