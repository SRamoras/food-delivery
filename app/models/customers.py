"""Customers and their delivery addresses."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, unique=True)
    phone: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"
    __table_args__ = (
        # Only rows with is_default = true enter this index, so a customer can have
        # many addresses but at most one default. Enforced by PostgreSQL, so two
        # simultaneous requests cannot both create a default.
        Index(
            "uq_customer_addresses_one_default",
            "customer_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        # Portuguese postcode, 0000-000: the only length rule on these text columns.
        CheckConstraint(r"postcode ~ '^[0-9]{4}-[0-9]{3}$'", name="postcode_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # CASCADE: an address means nothing without its customer. Orders keep their own
    # copy of the address, and customers with orders are protected by RESTRICT there.
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="RESTRICT"))
    street: Mapped[str] = mapped_column(Text)
    number: Mapped[str] = mapped_column(Text)
    floor: Mapped[str | None] = mapped_column(Text)
    postcode: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    # numeric(9,6) keeps exact coordinates, about 0.1 m of precision.
    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    lng: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
