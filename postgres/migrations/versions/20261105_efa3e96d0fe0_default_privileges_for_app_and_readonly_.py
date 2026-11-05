"""default privileges for app and readonly roles

Revision ID: efa3e96d0fe0
Revises:
Create Date: 2026-11-05

Every table and sequence that fd_owner creates in later migrations automatically
gets the grants below, so nobody has to remember a GRANT per table.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "efa3e96d0fe0"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Without USAGE a role cannot see anything inside the schema, whatever its
    # table grants. Not CREATE: only fd_owner (the schema owner) creates objects.
    op.execute("GRANT USAGE ON SCHEMA public TO fd_app, fd_readonly")

    # GRANT ... ON ALL TABLES only covers tables that exist now. DEFAULT PRIVILEGES
    # applies to every table fd_owner creates from now on (B's and C's included).
    # fd_app gets DML but no DDL (no ALTER/DROP/TRUNCATE), so a compromised app cannot
    # change the schema. B's migration later REVOKEs UPDATE, DELETE on
    # order_status_history to make it append-only.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fd_app"
    )
    # Identity/serial columns use a sequence: INSERT needs USAGE on it (nextval).
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO fd_app"
    )
    # fd_readonly: report export and DbGate only read.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner IN SCHEMA public "
        "GRANT SELECT ON TABLES TO fd_readonly"
    )


def downgrade() -> None:
    # Reverse order of upgrade(). Revoking default privileges only affects tables
    # created afterwards; this is the first migration, so no table exists yet.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner IN SCHEMA public "
        "REVOKE SELECT ON TABLES FROM fd_readonly"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM fd_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE fd_owner IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM fd_app"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM fd_app, fd_readonly")
