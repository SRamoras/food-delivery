"""Order tracking endpoint, polled by customers every few seconds."""

from fastapi import APIRouter

from app.schemas.tracking import OrderTracking
from app.services import tracking

router = APIRouter(prefix="/customers", tags=["tracking"])


@router.get("/{customer_id}/orders/{order_id}/track")
def track_order(customer_id: int, order_id: int) -> OrderTracking:
    """Show an order's status and its courier's last known position."""
    return tracking.get_tracking(customer_id, order_id)
