"""Alembic environment. Run through ``python -m synthcut_core.migrate``."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool, text
from synthcut_core import models  # noqa: F401 - registers tables on the metadata
from synthcut_core.db import Base

# Two containers starting at once must not both migrate. The lock is held on
# the single migration connection, so a pooled-connection mismatch cannot leak it.
MIGRATION_LOCK_KEY = 0x5C_C07_0001

config = context.config
target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
    with engine.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
        connection.commit()
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                transaction_per_migration=True,
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY})
            connection.commit()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
