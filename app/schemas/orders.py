"""Request and response models for placing and changing orders."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# Same list as CANCEL_REASONS in app/models/orders.py and the CHECK on orders.
# A Literal makes a reason outside the list a 422 at the door, instead of a 500 from
# the CHECK; tests/test_pricing.py fails if the two lists drift apart.
CancelReason = Literal[
    "customer_changed_mind",
    "restaurant_too_busy",
    "item_unavailable",
    "courier_unavailable",
    "payment_issue",
    "other",
]


class ChosenOption(BaseModel):
    """One choice the customer made for an item, checked against the menu by pricing."""

    type: str  # option group, e.g. "size"
    name: str  # choice inside the group, e.g. "large"


class OrderLineIn(BaseModel):
    """One line of a new order: which item, how many, and the chosen options."""

    item_id: int
    # le=50: a typo like 500 portions is refused before it touches the stock.
    quantity: int = Field(ge=1, le=50)
    options: list[ChosenOption] = []


class PlaceOrderIn(BaseModel):
    """Body of POST /customers/{customer_id}/orders (F2). Bad input → 422."""

    # A saved address id, so the service can check it belongs to this customer.
    address_id: int
    lines: list[OrderLineIn] = Field(min_length=1)
    tip: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)
    payment_method: Literal["card", "mbway", "cash"]
    simulate: Literal["approved", "declined"] = "approved"


class OrderOut(BaseModel):
    """The order as the API returns it, with the money totals."""

    id: int
    status: str
    restaurant_id: int
    subtotal: Decimal
    delivery_fee: Decimal
    tip: Decimal
    total: Decimal


class CancelIn(BaseModel):
    """Body of the cancel endpoints (F5): one of the fixed reasons."""

    reason: CancelReason


class StatusOut(BaseModel):
    """Answer of a status change (F5): the order and its new status."""

    id: int
    status: str
