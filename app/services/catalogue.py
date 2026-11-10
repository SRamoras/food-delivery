"""Catalogue reads for F1: restaurants open now for an address, and a restaurant's menu."""

from datetime import datetime

from sqlalchemy import Integer, cast, exists, func, select

from app.config import LISBON
from app.db.postgres import SessionLocal
from app.errors import NotFound
from app.models.customers import CustomerAddress
from app.models.geo import ZoneFee
from app.models.menu import MenuCategory, MenuItem
from app.models.ratings import Rating
from app.models.restaurants import OpeningPeriod, Restaurant
from app.schemas.catalogue import (
    MenuCategoryOut,
    MenuItemOut,
    RestaurantMenu,
    RestaurantSummary,
)


def list_open_restaurants(customer_id: int, address_id: int) -> list[RestaurantSummary]:
    """List restaurants open now (Lisbon time) that deliver to the customer's address.

    A restaurant qualifies with status 'open', a period containing this minute and a
    zone_fees row for the address's zone. Read-only, so it needs no locks.

    Raises:
        NotFound: the address does not exist or belongs to another customer.
    """
    # The server may run in UTC; opening hours are always Lisbon wall-clock time.
    now = datetime.now(LISBON)
    minute_of_day = now.hour * 60 + now.minute

    is_open_now = exists().where(
        OpeningPeriod.restaurant_id == Restaurant.id,
        OpeningPeriod.weekday == now.weekday(),
        # cast: psycopg may send a small number as smallint, and PostgreSQL has no
        # int4range @> smallint operator.
        OpeningPeriod.hours.contains(cast(minute_of_day, Integer)),
    )
    # NULL when the restaurant has no ratings yet.
    average_rating = (
        select(func.round(func.avg(Rating.restaurant_score), 2))
        .where(Rating.restaurant_id == Restaurant.id)
        .scalar_subquery()
    )

    with SessionLocal() as session, session.begin():
        zone_id = session.execute(
            select(CustomerAddress.zone_id).where(
                CustomerAddress.id == address_id,
                CustomerAddress.customer_id == customer_id,
            )
        ).scalar_one_or_none()
        if zone_id is None:
            raise NotFound("Address not found")

        rows = session.execute(
            select(
                Restaurant.id,
                Restaurant.name,
                Restaurant.min_order_value,
                ZoneFee.fee.label("delivery_fee"),
                average_rating.label("average_rating"),
            )
            .join(ZoneFee, ZoneFee.restaurant_zone_id == Restaurant.zone_id)
            .where(
                ZoneFee.customer_zone_id == zone_id,
                Restaurant.status == "open",
                is_open_now,
            )
            .order_by(Restaurant.name, Restaurant.id)
        ).all()

    return [RestaurantSummary.model_validate(row) for row in rows]


def get_menu(restaurant_id: int) -> RestaurantMenu:
    """Return a restaurant's categories, their items and each item's options.

    Unavailable items are included with their status, so the client can show them.

    Raises:
        NotFound: the restaurant does not exist.
    """
    with SessionLocal() as session, session.begin():
        restaurant = session.get(Restaurant, restaurant_id)
        if restaurant is None:
            raise NotFound("Restaurant not found")

        categories = session.scalars(
            select(MenuCategory)
            .where(MenuCategory.restaurant_id == restaurant_id)
            .order_by(MenuCategory.id)
        ).all()
        items = session.scalars(
            select(MenuItem)
            .join(MenuCategory, MenuItem.category_id == MenuCategory.id)
            .where(MenuCategory.restaurant_id == restaurant_id)
            .order_by(MenuItem.id)
        ).all()

    return RestaurantMenu(
        restaurant_id=restaurant_id,
        categories=[
            MenuCategoryOut(
                id=category.id,
                name=category.name,
                items=[
                    MenuItemOut.model_validate(item)
                    for item in items
                    if item.category_id == category.id
                ],
            )
            for category in categories
        ],
    )
