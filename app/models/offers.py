"""Delivery offers sent to couriers and the delivery a courier won (F3, F4)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base

OFFER_OUTCOMES = ("pending", "accepted", "rejected", "expired", "withdrawn")

# An offer is valid while pending and younger than this (checked lazily in F4).
OFFER_TTL_SECONDS = 45


class DeliveryOffer(Base):
    """One offer of one order to one courier, with its outcome."""

    __tablename__ = "delivery_offers"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('pending', 'accepted', 'rejected', 'expired', 'withdrawn')",
            name="outcome_valid",
        ),
        # The same order is never offered twice to the same courier (reoffer picks
        # the next couriers). Its index, led by order_id, also serves "every offer of
        # this order" (withdraw the others in F4, who was already offered in reoffer)
        # and the order_id foreign key.
        UniqueConstraint("order_id", "courier_id"),
        # Rule 1, second guard next to UNIQUE (order_id) on deliveries: at most one
        # accepted offer per order, even if the app has a bug.
        Index(
            "uq_delivery_offers_one_accepted_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("outcome = 'accepted'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: offers feed the reports (expired share per zone); deleting an order
    # or a courier must not erase them silently.
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    # Not indexed on purpose: no frequent query lists a courier's offers (F4 reads
    # the offer by id), and couriers are never deleted in normal use.
    courier_id: Mapped[int] = mapped_column(
        ForeignKey("couriers.id", ondelete="RESTRICT")
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    outcome: Mapped[str] = mapped_column(String(10), server_default=text("'pending'"))


class Delivery(Base):
    """The courier who won an order, and when they accepted, picked up and delivered it.

    Active (counts for the vehicle limit, rule 3) from accepted_at until delivered
    or the order is cancelled.
    """

    __tablename__ = "deliveries"
    __table_args__ = (
        CheckConstraint("distance_km >= 0", name="distance_km_nonneg"),
        # Times can only move forward, and nothing is delivered before it is picked up.
        CheckConstraint(
            "picked_up_at IS NULL OR picked_up_at >= accepted_at",
            name="picked_up_after_accepted",
        ),
        CheckConstraint(
            "delivered_at IS NULL"
            " OR (picked_up_at IS NOT NULL AND delivered_at >= picked_up_at)",
            name="delivered_after_picked_up",
        ),
        # EXPLAIN query 4 and the rule 3 count in F3/F4: a courier's deliveries not
        # yet delivered. Partial, so it only holds the few open ones, not the history.
        Index(
            "ix_deliveries_courier_active",
            "courier_id",
            postgresql_where=text("delivered_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # UNIQUE: rule 1, an order is assigned to exactly one courier. PostgreSQL's last
    # guarantee: a second INSERT for the same order fails, whatever the app does.
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), unique=True
    )
    # RESTRICT: a courier with deliveries is history (earnings report).
    courier_id: Mapped[int] = mapped_column(
        ForeignKey("couriers.id", ondelete="RESTRICT")
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Filled by B in F5 (picked_up, delivered).
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
