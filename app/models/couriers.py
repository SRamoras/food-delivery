"""Couriers, their vehicle and whether they may work."""

from sqlalchemy import CheckConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base

VEHICLE_TYPES = ("bicycle", "scooter", "car")
COURIER_STATUSES = ("active", "blocked")

# Rule 3: active deliveries allowed at the same time. Used by F3 (who has room)
# and F4 (re-checked with the courier row locked).
VEHICLE_CAPACITY = {"bicycle": 1, "scooter": 2, "car": 3}


class Courier(Base):
    __tablename__ = "couriers"
    __table_args__ = (
        CheckConstraint(
            "vehicle_type IN ('bicycle', 'scooter', 'car')", name="vehicle_type_valid"
        ),
        CheckConstraint("status IN ('active', 'blocked')", name="status_valid"),
        # Multi-column CHECK: a plate is mandatory for scooter and car and absent for
        # a bicycle. Two separate column rules could not express "depends on the other".
        CheckConstraint(
            "(vehicle_type = 'bicycle' AND licence_plate IS NULL)"
            " OR (vehicle_type <> 'bicycle' AND licence_plate IS NOT NULL)",
            name="plate_by_vehicle",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(10))
    # UNIQUE: two vehicles never share a plate. Bicycles have NULL, and NULLs never
    # collide in a UNIQUE, so any number of bicycles is allowed.
    licence_plate: Mapped[str | None] = mapped_column(String(10), unique=True)
    # blocked couriers cannot go online or accept offers (checked in F7 and F4).
    status: Mapped[str] = mapped_column(String(10), server_default=text("'active'"))
