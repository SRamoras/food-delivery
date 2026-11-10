"""Pydantic models for the order tracking response."""

from datetime import datetime

from pydantic import BaseModel


class CourierPosition(BaseModel):
    lat: float
    lng: float


class OrderTracking(BaseModel):
    order_id: int
    status: str
    courier_id: int | None
    courier_position: CourierPosition | None
    updated_at: datetime
