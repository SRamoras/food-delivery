"""Endpoints used by customers."""

from fastapi import APIRouter

from app.schemas.catalogue import RestaurantSummary
from app.services import catalogue

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("/{customer_id}/addresses/{address_id}/restaurants")
def list_restaurants(customer_id: int, address_id: int) -> list[RestaurantSummary]:
    """List restaurants open now that deliver to this address, with fee and rating."""
    return catalogue.list_open_restaurants(customer_id, address_id)
