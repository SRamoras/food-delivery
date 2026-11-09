"""Order endpoints: place (F2) and, later, status updates (F5)."""

from typing import Literal

from fastapi import APIRouter

from app.config import settings
from app.db.postgres import SessionLocal
from app.errors import NotFound
from app.schemas.orders import OrderOut, PlaceOrderIn
from app.services import orders as order_service
from app.services.side_effects import after_order_placed

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
