"""Pydantic models for the back-office report and ranking responses."""

from typing import Any

from pydantic import BaseModel


class ReportResult(BaseModel):
    report: str
    rows: list[dict[str, Any]]


class RankedRestaurant(BaseModel):
    restaurant_id: int
    deliveries: int


class RankingOut(BaseModel):
    city_id: int
    restaurants: list[RankedRestaurant]
