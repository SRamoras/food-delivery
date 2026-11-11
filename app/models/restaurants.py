"""Restaurants, their cuisines and their opening hours."""

from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import INT4RANGE, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base

# N:N association: the composite primary key stops the same pair appearing twice.
restaurant_cuisines = Table(
    "restaurant_cuisines",
    Base.metadata,
    Column(
        "restaurant_id",
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "cuisine_id",
        ForeignKey("cuisines.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class Cuisine(Base):
    __tablename__ = "cuisines"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)


class Restaurant(Base):
    __tablename__ = "restaurants"
    __table_args__ = (
        CheckConstraint("nif ~ '^[0-9]{9}$'", name="nif_format"),
        CheckConstraint("min_order_value >= 0", name="min_order_value_nonneg"),
        CheckConstraint("kitchen_capacity > 0", name="kitchen_capacity_positive"),
        CheckConstraint(
            "status IN ('open', 'closed', 'suspended')", name="status_valid"
        ),
        # EXPLAIN query 1: only open restaurants are ever searched by zone, so a
        # partial index stays smaller than one on every restaurant.
        Index(
            "ix_restaurants_zone_id_open",
            "zone_id",
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(Text)
    # Text, not a number: a NIF is an identifier and may start with 0.
    nif: Mapped[str] = mapped_column(Text, unique=True)
    address: Mapped[str] = mapped_column(Text)
    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    min_order_value: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    kitchen_capacity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default=text("'closed'"))


class OpeningPeriod(Base):
    """One period of a weekday; overlaps are refused by an EXCLUDE constraint.

    The EXCLUDE (no_overlap) is created with op.execute in the migration.
    """

    __tablename__ = "opening_periods"
    __table_args__ = (
        # 0 = Monday, matching Python's datetime.weekday().
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_valid"),
        # Minutes of the day, upper bound excluded: [0,1440) is 00:00 to 24:00.
        CheckConstraint(
            "NOT isempty(hours) AND hours <@ int4range(0, 1440)",
            name="hours_within_day",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE")
    )
    weekday: Mapped[int] = mapped_column(SmallInteger)
    hours: Mapped[Range[int]] = mapped_column(INT4RANGE)
