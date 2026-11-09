"""Menu categories and items, with their options stored as jsonb."""

from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_nonneg"),
        CheckConstraint("status IN ('available', 'unavailable')", name="status_valid"),
        # A CHECK passes on NULL, so items without a daily limit are still accepted.
        CheckConstraint("daily_stock >= 0", name="daily_stock_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # RESTRICT: order lines point at items, so a category cannot be removed by accident.
    category_id: Mapped[int] = mapped_column(
        ForeignKey("menu_categories.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(15), server_default=text("'available'"))
    # Configured portions per day; NULL means no limit. The daily_stock table holds
    # what is left today (Person B).
    daily_stock: Mapped[int | None] = mapped_column(Integer)
    # jsonb and not tables: option kinds change between restaurants and new ones need
    # no schema change. Validated by Pydantic. Not Mongo: prices are read in the same
    # transaction as the order.
    options: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'")
    )
