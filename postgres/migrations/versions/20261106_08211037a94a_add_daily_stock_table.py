"""add daily stock table: portions left per item per Lisbon day, one row per day so no midnight job

Revision ID: 08211037a94a
Revises: efa3e96d0fe0
Create Date: 2026-11-06 15:44:24.484731+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "08211037a94a"
# Provisional: must point at the catalogue migration that creates menu_items once it lands.
down_revision: str | Sequence[str] | None = "efa3e96d0fe0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create daily_stock, with non-negative stock enforced by PostgreSQL (rule 2)."""
    op.create_table(
        "daily_stock",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("stock_date", sa.Date(), nullable=False),
        sa.Column("remaining", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "remaining >= 0", name=op.f("ck_daily_stock_remaining_nonneg")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["menu_items.id"],
            name=op.f("fk_daily_stock_item_id_menu_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", "stock_date", name=op.f("pk_daily_stock")),
    )


def downgrade() -> None:
    """Drop daily_stock."""
    op.drop_table("daily_stock")
