"""Writes to Redis that follow a PostgreSQL commit. They never undo or fail the request."""

import logging

from app.services.orders import PlacedOrder
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
