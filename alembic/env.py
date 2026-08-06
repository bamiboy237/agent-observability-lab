"""This module configures Alembic for asynchronous PostgreSQL migrations."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.domain.evidence import models as evidence_models  # noqa: F401  (registers tables on Base)
from app.domain.support import models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models.Base.metadata


def database_configuration() -> dict[str, str]:
    return {"sqlalchemy.url": str(get_settings().migration_database_url)}


def run_migrations_offline() -> None:
    """This function runs migrations without a database connection."""
    context.configure(
        url=database_configuration()["sqlalchemy.url"],
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def apply_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """This function connects through the asynchronous driver.

    This function applies migrations that are pending.
    """
    engine = async_engine_from_config(
        database_configuration(),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with engine.connect() as connection:
        await connection.run_sync(apply_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
