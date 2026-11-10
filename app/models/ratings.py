"""Ratings given by customers after a delivered order."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        CheckConstraint(
            "restaurant_score BETWEEN 1 AND 5", name="restaurant_score_range"
        ),
        CheckConstraint("courier_score BETWEEN 1 AND 5", name="courier_score_range"),
        # F1 and EXPLAIN query 6: average rating of a restaurant, optionally by date.
        Index("ix_ratings_restaurant_id_created_at", "restaurant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # unique: each order is rated at most once.
    # RESTRICT: orders are financial records and are never removed in a cascade.
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), unique=True
    )
    # Copied from the order, which never changes restaurant: without it, every average
    # would have to go through all the orders of the restaurant.
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="RESTRICT")
    )
    restaurant_score: Mapped[int] = mapped_column(SmallInteger)
    courier_score: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
