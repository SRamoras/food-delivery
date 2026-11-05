"""Alembic environment: connects as fd_owner and compares migrations with the models."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.config import settings
from app.db.postgres import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Migrations always run as the owner role, never as fd_app (which cannot create
# tables) and never as the postgres superuser.
if not settings.migration_database_url:
    raise RuntimeError("MIGRATION_DATABASE_URL is not set (see .env.example)")
URL = settings.migration_database_url

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    context.configure(
        url=URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # NullPool: one short-lived connection, no pool kept for a one-off command.
    engine = create_engine(URL, poolclass=NullPool)
    with engine.connect() as connection:
        # compare_type / compare_server_default: autogenerate also detects changed
        # column types and defaults, not only new tables and columns.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        # PostgreSQL has transactional DDL: the whole upgrade commits or nothing does.
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
