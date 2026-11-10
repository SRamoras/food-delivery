"""Endpoints about restaurants."""

from fastapi import APIRouter

from app.schemas.catalogue import RestaurantMenu
from app.services import catalogue

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


@router.get("/{restaurant_id}/menu")
def get_menu(restaurant_id: int) -> RestaurantMenu:
    """Show a restaurant's menu, with the options of each item."""
    return catalogue.get_menu(restaurant_id)
