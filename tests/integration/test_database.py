import asyncio

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings


def database_url_or_skip() -> str:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for database integration tests")
    return str(settings.migration_database_url)


async def current_revision(database_url: str) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync_connection: MigrationContext.configure(
                    sync_connection
                ).get_current_revision()
            )
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_session_executes_select_one() -> None:
    database_url_or_skip()

    from app.db import get_session_factory

    async with get_session_factory()() as session:
        result = await session.execute(text("SELECT 1"))

    assert result.scalar_one() == 1


@pytest.mark.integration
def test_migrations_upgrade_downgrade_and_reapply() -> None:
    database_url = database_url_or_skip()
    alembic_config = Config("alembic.ini")
    head_revision = ScriptDirectory.from_config(alembic_config).get_current_head()

    command.upgrade(alembic_config, "head")
    assert asyncio.run(current_revision(database_url)) == head_revision

    command.downgrade(alembic_config, "base")
    assert asyncio.run(current_revision(database_url)) is None

    command.upgrade(alembic_config, "head")
    assert asyncio.run(current_revision(database_url)) == head_revision
