"""Quick tests for the order status transition check (no database needed)."""

import pytest

from app.errors import Conflict
from app.services.order_status import check_transition


@pytest.mark.parametrize(
    ("old", "new", "actor"),
    [
        (None, "placed", "customer"),
        ("placed", "accepted", "restaurant"),
        ("ready", "picked_up", "courier"),
        ("preparing", "cancelled", "backoffice"),
    ],
)
def test_allowed(old: str | None, new: str, actor: str) -> None:
    """A valid move by the right actor passes without raising."""
    check_transition(old, new, actor)


@pytest.mark.parametrize(
    ("old", "new", "actor"),
    [
        ("ready", "preparing", "restaurant"),
        ("picked_up", "cancelled", "customer"),
        ("placed", "rejected", "customer"),
        ("delivered", "cancelled", "backoffice"),
    ],
)
def test_refused(old: str | None, new: str, actor: str) -> None:
    """Backwards, too late, from a final status or by the wrong actor → Conflict (409)."""
    with pytest.raises(Conflict):
        check_transition(old, new, actor)
