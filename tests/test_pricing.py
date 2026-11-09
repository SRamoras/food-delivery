"""Quick tests for option pricing and the cancel reason list (no database needed)."""

from decimal import Decimal
from typing import get_args

import pytest
from pydantic import ValidationError

from app.errors import Conflict
from app.models.orders import CANCEL_REASONS
from app.schemas.orders import CancelIn, CancelReason, ChosenOption
from app.services.pricing import price_line

# Same shape as C's menu_items.options jsonb (numbers arrive as int/float).
OPTIONS = [
    {
        "type": "size",
        "required": True,
        "choices": [{"name": "small", "extra": 0}, {"name": "large", "extra": 2.10}],
    },
    {"type": "extras", "max": 3, "choices": [{"name": "cheese", "extra": 1.00}]},
    {"type": "allergens", "values": ["gluten"]},
]


def opt(type_: str, name: str) -> ChosenOption:
    return ChosenOption(type=type_, name=name)


def test_price_adds_extras_without_float_errors() -> None:
    unit, snapshot = price_line(
        Decimal("9.50"), OPTIONS, [opt("size", "large"), opt("extras", "cheese")]
    )
    assert unit == Decimal("12.60")
    assert snapshot == [
        {"type": "size", "name": "large", "extra": "2.10"},
        {"type": "extras", "name": "cheese", "extra": "1.00"},
    ]


@pytest.mark.parametrize(
    "chosen",
    [
        [opt("sauce", "bbq")],  # unknown group
        [opt("size", "huge")],  # unknown choice
        [opt("allergens", "gluten")],  # information only, not choosable
        [opt("size", "small"), opt("size", "large")],  # no max means one
        [opt("extras", "cheese")],  # required size missing
    ],
)
def test_invalid_choices_are_refused(chosen: list[ChosenOption]) -> None:
    with pytest.raises(Conflict):
        price_line(Decimal("9.50"), OPTIONS, chosen)


def test_cancel_reasons_match_the_model_and_the_check() -> None:
    assert set(get_args(CancelReason)) == set(CANCEL_REASONS)


def test_cancel_reason_outside_the_list_is_a_422() -> None:
    with pytest.raises(ValidationError):
        CancelIn(reason="took too long")
