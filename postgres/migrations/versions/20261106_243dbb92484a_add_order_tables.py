"""add order tables: orders, lines, payments and an append-only status history

Revision ID: 243dbb92484a
Revises: 08211037a94a
Create Date: 2026-11-06 16:05:38.501710+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "243dbb92484a"
down_revision: str | Sequence[str] | None = "08211037a94a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out here, not imported from the models: a migration must keep creating the
# same schema even if the application's lists change later.
ORDER_STATUSES = (
    "'placed', 'accepted', 'preparing', 'ready', "
    "'picked_up', 'delivered', 'cancelled', 'rejected'"
)
ACTIVE_KITCHEN_STATUSES = "'accepted', 'preparing', 'ready'"
ACTOR_TYPES = "'customer', 'restaurant', 'courier', 'backoffice', 'system'"
CANCEL_ACTORS = "'customer', 'restaurant', 'backoffice'"
CANCEL_REASONS = (
    "'customer_changed_mind', 'restaurant_too_busy', 'item_unavailable', "
    "'courier_unavailable', 'payment_issue', 'other'"
)


def upgrade() -> None:
    """Create the order tables and take UPDATE and DELETE on the history from fd_app."""
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("source_address_id", sa.Integer(), nullable=True),
        sa.Column("delivery_street", sa.Text(), nullable=False),
        sa.Column("delivery_number", sa.String(length=20), nullable=False),
        sa.Column("delivery_floor", sa.String(length=20), nullable=True),
        sa.Column("delivery_postcode", sa.String(length=8), nullable=False),
        sa.Column("delivery_zone_id", sa.Integer(), nullable=False),
        sa.Column("delivery_lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("delivery_lng", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("delivery_notes", sa.Text(), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "tip",
            sa.Numeric(precision=10, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("total", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'placed'"),
            nullable=False,
        ),
        sa.Column("cancel_reason", sa.String(length=30), nullable=True),
        sa.Column("cancelled_by", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("subtotal >= 0", name=op.f("ck_orders_subtotal_nonneg")),
        sa.CheckConstraint(
            "delivery_fee >= 0", name=op.f("ck_orders_delivery_fee_nonneg")
        ),
        sa.CheckConstraint("tip >= 0", name=op.f("ck_orders_tip_nonneg")),
        sa.CheckConstraint("total >= 0", name=op.f("ck_orders_total_nonneg")),
        sa.CheckConstraint(
            "total = subtotal + delivery_fee + tip", name=op.f("ck_orders_total_sum")
        ),
        sa.CheckConstraint(
            f"status IN ({ORDER_STATUSES})", name=op.f("ck_orders_status_valid")
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_by IS NOT NULL)",
            name=op.f("ck_orders_cancelled_by_iff_cancelled"),
        ),
        sa.CheckConstraint(
            "status <> 'cancelled' OR cancel_reason IS NOT NULL",
            name=op.f("ck_orders_cancel_has_reason"),
        ),
        sa.CheckConstraint(
            f"cancelled_by IS NULL OR cancelled_by IN ({CANCEL_ACTORS})",
            name=op.f("ck_orders_cancelled_by_valid"),
        ),
        sa.CheckConstraint(
            f"cancel_reason IS NULL OR cancel_reason IN ({CANCEL_REASONS})",
            name=op.f("ck_orders_cancel_reason_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_orders_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name=op.f("fk_orders_restaurant_id_restaurants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_address_id"],
            ["customer_addresses.id"],
            name=op.f("fk_orders_source_address_id_customer_addresses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_zone_id"],
            ["zones.id"],
            name=op.f("fk_orders_delivery_zone_id_zones"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    # EXPLAIN query 2: a customer's orders, newest first. Also serves the FK.
    op.create_index(
        "ix_orders_customer_id_created_at",
        "orders",
        ["customer_id", sa.text("created_at DESC")],
    )
    # EXPLAIN query 3 and the kitchen capacity count: only active orders.
    op.create_index(
        "ix_orders_restaurant_active",
        "orders",
        ["restaurant_id", "created_at"],
        postgresql_where=sa.text(f"status IN ({ACTIVE_KITCHEN_STATUSES})"),
    )

    op.create_table(
        "order_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("item_name", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity >= 1", name=op.f("ck_order_lines_quantity_pos")),
        sa.CheckConstraint(
            "unit_price >= 0", name=op.f("ck_order_lines_unit_price_nonneg")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(options) = 'array'",
            name=op.f("ck_order_lines_options_is_array"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_lines_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["menu_items.id"],
            name=op.f("fk_order_lines_item_id_menu_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_lines")),
    )
    op.create_index(op.f("ix_order_lines_order_id"), "order_lines", ["order_id"])

    op.create_table(
        "order_status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"new_status IN ({ORDER_STATUSES})",
            name=op.f("ck_order_status_history_new_status_valid"),
        ),
        sa.CheckConstraint(
            f"old_status IS NULL OR old_status IN ({ORDER_STATUSES})",
            name=op.f("ck_order_status_history_old_status_valid"),
        ),
        sa.CheckConstraint(
            "old_status IS DISTINCT FROM new_status",
            name=op.f("ck_order_status_history_status_changes"),
        ),
        sa.CheckConstraint(
            f"actor_type IN ({ACTOR_TYPES})",
            name=op.f("ck_order_status_history_actor_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_status_history_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_status_history")),
    )
    # The order's timeline in order; also serves the FK.
    op.create_index(
        "ix_order_status_history_order_id_changed_at",
        "order_status_history",
        ["order_id", "changed_at"],
    )
    # Append-only history: fd_app got UPDATE and DELETE from the default privileges when
    # fd_owner created the table above, so even a bug in the app could rewrite it.
    op.execute("REVOKE UPDATE, DELETE ON order_status_history FROM fd_app")

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column(
            "paid_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("provider_ref", sa.String(length=64), nullable=True),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_payments_amount_nonneg")),
        sa.CheckConstraint(
            "method IN ('card', 'mbway', 'cash')", name=op.f("ck_payments_method_valid")
        ),
        sa.CheckConstraint(
            "status IN ('approved', 'declined', 'refunded')",
            name=op.f("ck_payments_status_valid"),
        ),
        sa.CheckConstraint(
            "(method = 'cash' AND provider_ref IS NULL)"
            " OR (method IN ('card', 'mbway') AND provider_ref IS NOT NULL)",
            name=op.f("ck_payments_provider_ref_by_method"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_payments_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("provider_ref", name=op.f("uq_payments_provider_ref")),
    )
    op.create_index(op.f("ix_payments_order_id"), "payments", ["order_id"])
    # An order is paid at most once and refunded at most once, even if two cancels race.
    op.create_index(
        "uq_payments_one_approved_per_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )
    op.create_index(
        "uq_payments_one_refund_per_order",
        "payments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'refunded'"),
    )


def downgrade() -> None:
    """Drop the order tables, children first; their indexes and grants go with them."""
    op.drop_table("payments")
    op.drop_table("order_status_history")
    op.drop_table("order_lines")
    op.drop_table("orders")
