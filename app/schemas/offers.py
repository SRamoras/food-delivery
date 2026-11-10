"""Request and response bodies for the restaurant decisions and delivery offers (F3)."""

from pydantic import BaseModel

from app.schemas.orders import CancelReason


class RejectIn(BaseModel):
    """Body of the reject endpoint: a reason from the fixed list is optional."""

    reason: CancelReason | None = None


class SentOfferOut(BaseModel):
    offer_id: int
    courier_id: int


class OfferedOut(BaseModel):
    """Answer of accept and reoffer: the order, its status and the offers just sent."""

    id: int
    status: str
    offers: list[SentOfferOut]


class OfferAnswerOut(BaseModel):
    """Answer of a courier's accept or decline (F4): the offer and its new outcome."""

    offer_id: int
    order_id: int
    courier_id: int
    outcome: str
