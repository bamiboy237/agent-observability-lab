"""Test runtime checks that protect the PostgreSQL sandbox target."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.engine import make_url

from app.domain.simulation.errors import EnvironmentRunError
from app.domain.simulation.postgres import PostgresSandboxTarget, PostgresSupportSandbox
from app.domain.simulation.scenarios import SCENARIO_BY_ID

DATABASE_URL = "postgresql+asyncpg://sandbox_role:secret@sandbox.local:5432/sandbox_db"


def test_sandbox_target_requires_test_environment() -> None:
    with pytest.raises(ValueError, match="ENVIRONMENT=test"):
        PostgresSandboxTarget.from_database_url(DATABASE_URL, environment="production")


async def test_sandbox_rejects_session_on_an_unapproved_host() -> None:
    target = PostgresSandboxTarget.from_database_url(DATABASE_URL, environment="test")
    session = Mock()
    session.get_bind.return_value.engine.url = make_url(
        "postgresql+asyncpg://sandbox_role:secret@production.local:5432/sandbox_db"
    )
    sandbox = PostgresSupportSandbox(
        session,
        SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"],
        isolation_confirmed=True,
        target=target,
    )

    with pytest.raises(EnvironmentRunError, match="session host"):
        await sandbox.verify_target()


async def test_sandbox_rejects_unapproved_server_database_or_role() -> None:
    target = PostgresSandboxTarget.from_database_url(DATABASE_URL, environment="test")
    session = Mock()
    session.get_bind.return_value.engine.url = make_url(DATABASE_URL)
    result = Mock()
    result.one.return_value = SimpleNamespace(
        database_name="production_db",
        role_name="sandbox_role",
    )
    session.execute = AsyncMock(return_value=result)
    sandbox = PostgresSupportSandbox(
        session,
        SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"],
        isolation_confirmed=True,
        target=target,
    )

    with pytest.raises(EnvironmentRunError, match="server database or role"):
        await sandbox.verify_target()
