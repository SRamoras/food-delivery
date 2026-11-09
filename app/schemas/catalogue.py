"""Pydantic models for the catalogue: item options, restaurant list and menu."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OptionChoice(BaseModel):
    name: str
    extra: Decimal = Field(ge=0, decimal_places=2)


class ChoiceOption(BaseModel):
    type: str
    required: bool = False
    max: int | None = Field(default=None, ge=1)
    choices: list[OptionChoice] = Field(min_length=1)


class LabelOption(BaseModel):
    type: str
    values: list[str]


# `type` is free text on purpose: a new kind of option (e.g. "cooking point") only has
# to follow one of these two shapes, with no change to the code or the database.
ItemOption = ChoiceOption | LabelOption


class RestaurantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    min_order_value: Decimal
    delivery_fee: Decimal
    average_rating: Decimal | None


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    price: Decimal
    status: str
    options: list[ItemOption]


class MenuCategoryOut(BaseModel):
    id: int
    name: str
    items: list[MenuItemOut]


class RestaurantMenu(BaseModel):
    restaurant_id: int
    categories: list[MenuCategoryOut]
