"""text columns instead of varchar

Revision ID: 2d36777303ad
Revises: 00607fce83ed
Create Date: 2026-11-11 05:26:35.053777+00:00

The course rules ask for `text` unless a length limit is a real business rule. The
varchar lengths were arbitrary (names of 100, 200 or 255) or repeated a rule a CHECK
already enforces (statuses, methods, vehicle types, the 9-digit NIF). The only length
that is a business rule is the Portuguese postcode, so it gets a format CHECK, which is
stronger than a maximum length.

varchar -> text is binary compatible in PostgreSQL: no table rewrite, and the unique and
partial indexes stay valid, so this runs in milliseconds on the seeded data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2d36777303ad"
down_revision: str | Sequence[str] | None = "00607fce83ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, previous varchar length): the downgrade puts each length back.
COLUMNS = [
    ("cities", "name", 100),
    ("zones", "name", 100),
    ("customers", "name", 200),
    ("customers", "email", 255),
    ("customers", "phone", 20),
    ("customers", "password_hash", 255),
    ("customer_addresses", "street", 200),
    ("customer_addresses", "number", 20),
    ("customer_addresses", "floor", 20),
    ("customer_addresses", "postcode", 8),
    ("cuisines", "name", 50),
    ("restaurants", "name", 200),
    ("restaurants", "nif", 9),
    ("restaurants", "address", 300),
    ("restaurants", "status", 10),
    ("menu_categories", "name", 100),
    ("menu_items", "name", 200),
    ("menu_items", "status", 15),
    ("couriers", "name", 200),
    ("couriers", "email", 255),
    ("couriers", "phone", 20),
    ("couriers", "vehicle_type", 10),
    ("couriers", "licence_plate", 10),
    ("couriers", "status", 10),
    ("orders", "delivery_number", 20),
    ("orders", "delivery_floor", 20),
    ("orders", "delivery_postcode", 8),
    ("orders", "status", 20),
    ("orders", "cancel_reason", 30),
    ("orders", "cancelled_by", 20),
    ("order_status_history", "old_status", 20),
    ("order_status_history", "new_status", 20),
    ("order_status_history", "actor_type", 20),
    ("payments", "method", 10),
    ("payments", "status", 10),
    ("payments", "provider_ref", 64),
    ("delivery_offers", "outcome", 10),
]

# Portuguese postcode: 4 digits, a hyphen, 3 digits (e.g. 1000-001).
POSTCODE_CHECKS = [
    ("customer_addresses", "postcode_format", "postcode"),
    ("orders", "delivery_postcode_format", "delivery_postcode"),
]


def upgrade() -> None:
    """Every varchar becomes text; the postcode gets its format CHECK."""
    for table, column, length in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Text(),
            existing_type=sa.String(length),
        )
    for table, name, column in POSTCODE_CHECKS:
        op.create_check_constraint(name, table, f"{column} ~ '^[0-9]{{4}}-[0-9]{{3}}$'")


def downgrade() -> None:
    """Drop the postcode CHECKs and put every varchar length back."""
    for table, name, _ in POSTCODE_CHECKS:
        # op.f(): the full name, so the naming convention is not applied twice.
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    for table, column, length in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.String(length),
            existing_type=sa.Text(),
        )
