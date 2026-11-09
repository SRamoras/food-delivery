"""Cities, delivery zones and the fee between each pair of zones."""

from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Zone(Base):
    __tablename__ = "zones"
    # Per city, not global: two cities can each have a zone called "Centro".
    __table_args__ = (UniqueConstraint("city_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: a city with zones cannot disappear and take addresses with it.
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(100))


class ZoneFee(Base):
    """Delivery fee for a pair of zones; no row means the pair is not delivered."""

    __tablename__ = "zone_fees"
    __table_args__ = (
        UniqueConstraint("restaurant_zone_id", "customer_zone_id"),
        CheckConstraint("fee >= 0", name="fee_nonneg"),
        # The UNIQUE above starts with restaurant_zone_id, so it cannot answer
        # "which zones deliver to this customer zone?" (EXPLAIN query 1).
        Index("ix_zone_fees_customer_zone_id", "customer_zone_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_zone_id: Mapped[int] = mapped_column(
        ForeignKey("zones.id", ondelete="RESTRICT")
    )
    customer_zone_id: Mapped[int] = mapped_column(
        ForeignKey("zones.id", ondelete="RESTRICT")
    )
    fee: Mapped[Decimal] = mapped_column(Numeric(10, 2))
