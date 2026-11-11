"""Orders, order lines, status history and daily stock (Person B)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base

ORDER_STATUSES = (
    "placed",
    "accepted",
    "preparing",
    "ready",
    "picked_up",
    "delivered",
    "cancelled",
    "rejected",
)
ACTIVE_KITCHEN_STATUSES = ("accepted", "preparing", "ready")
ACTOR_TYPES = ("customer", "restaurant", "courier", "backoffice", "system")
CANCEL_ACTORS = ("customer", "restaurant", "backoffice")
CANCEL_REASONS = (
    "customer_changed_mind",
    "restaurant_too_busy",
    "item_unavailable",
    "courier_unavailable",
    "payment_issue",
    "other",
)
MONEY = Numeric(10, 2)


def _in(values: tuple[str, ...]) -> str:
    """SQL list for a CHECK, built from constants in this file (never from input)."""
    return ", ".join(f"'{v}'" for v in values)


class DailyStock(Base):
    """Portions left of one item on one Lisbon day. Created on first use (lazy reset)."""

    __tablename__ = "daily_stock"
    __table_args__ = (
        # Last line of defence for rule 2: even a buggy write cannot sell what is not there.
        CheckConstraint("remaining >= 0", name="remaining_nonneg"),
    )

    # ON DELETE CASCADE: the stock of a deleted item has no meaning.
    item_id: Mapped[int] = mapped_column(
        ForeignKey("menu_items.id", ondelete="CASCADE"), primary_key=True
    )
    stock_date: Mapped[date] = mapped_column(Date, primary_key=True)
    remaining: Mapped[int] = mapped_column(Integer)


class Order(Base):
    """One customer order, with a snapshot of the delivery address and the money totals."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="subtotal_nonneg"),
        CheckConstraint("delivery_fee >= 0", name="delivery_fee_nonneg"),
        CheckConstraint("tip >= 0", name="tip_nonneg"),
        CheckConstraint("total >= 0", name="total_nonneg"),
        # The total can never drift from its parts (catches rounding bugs).
        CheckConstraint("total = subtotal + delivery_fee + tip", name="total_sum"),
        # Same format as customer_addresses.postcode, which this column snapshots.
        CheckConstraint(
            r"delivery_postcode ~ '^[0-9]{4}-[0-9]{3}$'",
            name="delivery_postcode_format",
        ),
        CheckConstraint(f"status IN ({_in(ORDER_STATUSES)})", name="status_valid"),
        # A cancelled order always says who and why; no other status has a cancel actor.
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_by IS NOT NULL)",
            name="cancelled_by_iff_cancelled",
        ),
        CheckConstraint(
            "status <> 'cancelled' OR cancel_reason IS NOT NULL",
            name="cancel_has_reason",
        ),
        CheckConstraint(
            f"cancelled_by IS NULL OR cancelled_by IN ({_in(CANCEL_ACTORS)})",
            name="cancelled_by_valid",
        ),
        # A fixed list, so pipeline 4 groups without spelling variations.
        CheckConstraint(
            f"cancel_reason IS NULL OR cancel_reason IN ({_in(CANCEL_REASONS)})",
            name="cancel_reason_valid",
        ),
        # EXPLAIN query 2: a customer's orders, newest first. Also serves the FK.
        Index(
            "ix_orders_customer_id_created_at", "customer_id", text("created_at DESC")
        ),
        # EXPLAIN query 3 and the kitchen capacity count: only active orders.
        Index(
            "ix_orders_restaurant_active",
            "restaurant_id",
            "created_at",
            postgresql_where=text(f"status IN ({_in(ACTIVE_KITCHEN_STATUSES)})"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: orders are financial records; they never disappear in a cascade.
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT")
    )
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="RESTRICT")
    )

    # Address snapshot: where this order went that day, not the customer's current address.
    # SET NULL: the snapshot is the truth; the link to the saved address is only informative.
    source_address_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer_addresses.id", ondelete="SET NULL")
    )
    delivery_street: Mapped[str] = mapped_column(Text)
    delivery_number: Mapped[str] = mapped_column(Text)
    delivery_floor: Mapped[str | None] = mapped_column(Text)
    delivery_postcode: Mapped[str] = mapped_column(Text)
    delivery_zone_id: Mapped[int] = mapped_column(
        ForeignKey("zones.id", ondelete="RESTRICT")
    )
    delivery_lat: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    delivery_lng: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    delivery_notes: Mapped[str | None] = mapped_column(Text)

    subtotal: Mapped[Decimal] = mapped_column(MONEY)
    delivery_fee: Mapped[Decimal] = mapped_column(MONEY)
    tip: Mapped[Decimal] = mapped_column(MONEY, server_default=text("0"))
    total: Mapped[Decimal] = mapped_column(MONEY)

    status: Mapped[str] = mapped_column(Text, server_default=text("'placed'"))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    # Also in the history; kept here so the report export needs no join.
    cancelled_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OrderLine(Base):
    """An item of an order, with the unit price (item + options) at order time."""

    __tablename__ = "order_lines"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="quantity_pos"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonneg"),
        CheckConstraint("jsonb_typeof(options) = 'array'", name="options_is_array"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # CASCADE: lines have no meaning without their order. Indexed: every read loads them.
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    # Not indexed on purpose: no frequent query filters lines by item.
    item_id: Mapped[int] = mapped_column(
        ForeignKey("menu_items.id", ondelete="RESTRICT")
    )
    item_name: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(MONEY)
    # Chosen options and the extra paid for each, frozen at order time.
    options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )


class OrderStatusHistory(Base):
    """Append-only log of every status change (fd_app has no UPDATE/DELETE on it)."""

    __tablename__ = "order_status_history"
    __table_args__ = (
        CheckConstraint(
            f"new_status IN ({_in(ORDER_STATUSES)})", name="new_status_valid"
        ),
        CheckConstraint(
            f"old_status IS NULL OR old_status IN ({_in(ORDER_STATUSES)})",
            name="old_status_valid",
        ),
        CheckConstraint(
            "old_status IS DISTINCT FROM new_status", name="status_changes"
        ),
        CheckConstraint(f"actor_type IN ({_in(ACTOR_TYPES)})", name="actor_type_valid"),
        # The order's timeline in order; also serves the FK.
        Index("ix_order_status_history_order_id_changed_at", "order_id", "changed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: the history can never be removed by a cascade.
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    old_status: Mapped[str | None] = mapped_column(Text)  # NULL at order creation
    new_status: Mapped[str] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(Integer)  # NULL for backoffice/system
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
