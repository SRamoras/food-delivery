"""Quick tests for the straight-line delivery distance (no database needed)."""

from decimal import Decimal

from app.services.orders import distance_km


def test_same_point_is_zero() -> None:
    """Restaurant and address at the same spot: 0 km."""
    assert distance_km(38.7223, -9.1393, 38.7223, -9.1393) == Decimal("0.00")


def test_lisbon_to_porto() -> None:
    """Lisbon to Porto is about 274 km in a straight line, rounded to 2 decimals."""
    km = distance_km(38.7223, -9.1393, 41.1579, -8.6291)
    assert Decimal(270) < km < Decimal(280)
    assert km == km.quantize(Decimal("0.01"))
