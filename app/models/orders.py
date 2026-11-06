"""Orders, order lines, status history and daily stock (Person B)."""

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


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
