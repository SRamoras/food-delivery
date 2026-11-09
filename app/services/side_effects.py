"""Writes to Redis that follow a PostgreSQL commit. They never undo or fail the request."""

import logging
from datetime import datetime

from app.config import LISBON
from app.services.orders import PlacedOrder, StatusChange
from app.services.stock import write_stock_copies

log = logging.getLogger(__name__)


def after_order_placed(placed: PlacedOrder) -> None:
    """Copy the new stock to Redis. PostgreSQL has already committed the order.

    A Redis failure here must not become a 500: the order exists and the customer was
    charged. The key is derived data, so redis/verify.py finds the gap and
    redis/rebuild.py fixes it. The tracking key (C's function) is added here later.
    """
    try:
        write_stock_copies(placed.stock_after, placed.stock_date)
    except Exception:
        log.exception("fd:stock update failed for order %s", placed.order.id)


def after_status_change(change: StatusChange) -> None:
    """Copy the stock given back by a cancel to Redis. PostgreSQL has already committed.

    Only today's key: yesterday's stock is never read again. The tracking key (C's
    function) is added here later.
    """
    if not change.stock_after or change.stock_date != datetime.now(LISBON).date():
        return
    try:
        write_stock_copies(change.stock_after, change.stock_date)
    except Exception:
        log.exception("fd:stock update failed for order %s", change.order.id)
