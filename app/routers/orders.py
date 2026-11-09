"""Order endpoints: place (F2) and, later, status updates (F5)."""

from fastapi import APIRouter

from app.db.postgres import SessionLocal
from app.schemas.orders import OrderOut, PlaceOrderIn
from app.services import orders as order_service

router = APIRouter(tags=["orders"])


# `def`, not `async def`: FastAPI runs it in its thread pool, so simultaneous orders
# reach PostgreSQL in parallel (what the last-portions test needs).
@router.post(
    "/customers/{customer_id}/orders", status_code=201, response_model=OrderOut
)
def place_order(customer_id: int, body: PlaceOrderIn) -> OrderOut:
    """Place an order: restaurant, items, minimum and daily stock checked in one transaction."""
    # Commits at the end of the block; a 404/409 raised inside rolls everything back.
    with SessionLocal() as session, session.begin():
        placed = order_service.place_order(session, customer_id, body)
    return OrderOut.model_validate(placed.order, from_attributes=True)
