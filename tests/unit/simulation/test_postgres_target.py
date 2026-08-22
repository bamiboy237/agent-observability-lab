"""Test runtime checks that protect the PostgreSQL sandbox target."""

from unittest.mock import AsyncMock, Mock

from app.domain.simulation.postgres import PostgresSandboxTarget, PostgresSupportSandbox
from app.domain.simulation.scenarios import SCENARIO_BY_ID

DATABASE_URL = "postgresql+asyncpg://sandbox_role:secret@sandbox.local:5432/sandbox_db"


def test_sandbox_target_parses_database_url() -> None:
    target = PostgresSandboxTarget.from_database_url(DATABASE_URL)
    assert target.host == "sandbox.local"
    assert target.port == 5432
    assert target.database == "sandbox_db"
    assert target.role == "sandbox_role"


async def test_sandbox_verify_target_prepares_session() -> None:
    target = PostgresSandboxTarget.from_database_url(DATABASE_URL, environment="test")
    session = Mock()
    session.execute = AsyncMock()
    sandbox = PostgresSupportSandbox(
        session,
        SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"],
        isolation_confirmed=True,
        target=target,
    )

    await sandbox.verify_target()
    assert sandbox._target_verified is True
    assert session.execute.call_count > 0
