"""Simulated payments and refunds (Person B)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Payment(Base):
    """A payment or refund of an order. A refund is a new row, never an edit."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_nonneg"),
        CheckConstraint("method IN ('card', 'mbway', 'cash')", name="method_valid"),
        CheckConstraint(
            "status IN ('approved', 'declined', 'refunded')", name="status_valid"
        ),
        # Cash never goes through a provider; card and MB WAY always have a reference.
        CheckConstraint(
            "(method = 'cash' AND provider_ref IS NULL)"
            " OR (method IN ('card', 'mbway') AND provider_ref IS NOT NULL)",
            name="provider_ref_by_method",
        ),
        # An order is paid at most once and refunded at most once, even if two cancels race.
        Index(
            "uq_payments_one_approved_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
        Index(
            "uq_payments_one_refund_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("status = 'refunded'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: financial records never disappear in a cascade. Indexed: read per order.
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    method: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # UNIQUE: a provider reference is never recorded twice. NULLs (cash) do not collide.
    provider_ref: Mapped[str | None] = mapped_column(Text, unique=True)
