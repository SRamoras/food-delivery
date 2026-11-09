"""Unit price of an order line: item price plus the extras of the chosen options."""

from decimal import Decimal
from typing import Any

from app.errors import Conflict
from app.schemas.orders import ChosenOption

CENT = Decimal("0.01")


def price_line(
    item_price: Decimal, item_options: list[dict[str, Any]], chosen: list[ChosenOption]
) -> tuple[Decimal, list[dict[str, str]]]:
    """Return (unit_price, options_snapshot) for one line. Invalid choices → 409.

    The item's options come from the menu_items jsonb. The snapshot keeps the extra
    paid for each choice, so a later menu price change does not change this order.
    """
    # Only groups with "choices" can be chosen; "allergens" is information only.
    groups = {g["type"]: g for g in item_options if "choices" in g}
    count: dict[str, int] = {}
    unit = Decimal(item_price)
    snapshot: list[dict[str, str]] = []
    for c in chosen:
        group = groups.get(c.type)
        if group is None:
            raise Conflict(f"unknown option {c.type}")
        choice = next((ch for ch in group["choices"] if ch["name"] == c.name), None)
        if choice is None:
            raise Conflict(f"unknown choice {c.name} for {c.type}")
        count[c.type] = count.get(c.type, 0) + 1
        # No "max" means one choice: nothing is unlimited unless the menu says so.
        if count[c.type] > group.get("max", 1):
            raise Conflict(f"too many choices for {c.type}")
        # jsonb numbers arrive as float; str() first avoids Decimal(2.1) = 2.1000000000000000888...
        extra = Decimal(str(choice.get("extra", 0))).quantize(CENT)
        unit += extra
        # Stored as a string so the jsonb snapshot keeps the exact cents.
        snapshot.append({"type": c.type, "name": c.name, "extra": str(extra)})
    for name, group in groups.items():
        if group.get("required") and name not in count:
            raise Conflict(f"option {name} is required")
    return unit.quantize(CENT), snapshot
