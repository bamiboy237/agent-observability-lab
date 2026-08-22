"""This module tests evidence storage against PostgreSQL for checkpoint 3.4.

Reimporting unchanged evidence does not duplicate it.
Changed evidence creates a visible new import version.
Tests run only against the configured isolated database.
"""


import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.config import Settings
from app.db import get_session_factory
from app.domain.evidence.models import TraceImport
from app.domain.evidence.service import ImportStatus, TraceImportService
from app.domain.evidence.store import SqlAlchemyEvidenceStore


@pytest.fixture(scope="module", autouse=True)
def apply_evidence_migrations() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for evidence integration tests")
    command.upgrade(Config("alembic.ini"), "head")


@pytest.mark.integration
async def test_postgres_import_is_idempotent_and_versions_changes() -> None:
    fixture_source = FixtureTraceSource()
    evidence = await fixture_source.fetch_trace("phase2-01-bad-prompt-policy-answer")
    evidence_id = evidence.evidence_id

    try:
        async with get_session_factory().begin() as session:
            await session.execute(delete(TraceImport).where(TraceImport.evidence_id == evidence_id))
        async with get_session_factory().begin() as session:
            service = TraceImportService(SqlAlchemyEvidenceStore(session))
            first = await service.import_evidence(evidence)
            second = await service.import_evidence(evidence)
            changed = evidence.model_copy(update={"retry_count": evidence.retry_count + 1})
            third = await service.import_evidence(changed)

        assert first.status is ImportStatus.CREATED
        assert first.import_version == 1
        assert second.status is ImportStatus.UNCHANGED
        assert second.import_version == 1
        assert third.status is ImportStatus.UPDATED
        assert third.import_version == 2
        assert third.evidence_id == first.evidence_id

        async with get_session_factory()() as session:
            rows = (
                (
                    await session.execute(
                        select(TraceImport)
                        .where(TraceImport.evidence_id == evidence_id)
                        .order_by(TraceImport.import_version)
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 2
        assert [row.import_version for row in rows] == [1, 2]
        assert rows[0].content_hash != rows[1].content_hash
        assert rows[0].source_platform == "langsmith"
        assert rows[0].source_project == "agent-reliability-lab"
        assert rows[0].scenario_id == "phase2-01-bad-prompt-policy-answer"
        assert rows[0].outcome == "blocked"
        assert rows[0].reason_code == "policy_answer_ungrounded"
        assert rows[0].source_url and rows[0].source_url.startswith("https://smith.langchain.com/")
        assert rows[1].evidence_json["retry_count"] == 1
    finally:
        async with get_session_factory().begin() as session:
            await session.execute(delete(TraceImport).where(TraceImport.evidence_id == evidence_id))


@pytest.mark.integration
async def test_postgres_stores_two_distinct_traces_without_duplicates() -> None:
    fixture_source = FixtureTraceSource()
    first_evidence = await fixture_source.fetch_trace("phase2-05-unconfirmed-refund")
    second_evidence = await fixture_source.fetch_trace("phase2-07-slow-database")

    try:
        async with get_session_factory().begin() as session:
            await session.execute(
                delete(TraceImport).where(
                    TraceImport.evidence_id.in_(
                        [first_evidence.evidence_id, second_evidence.evidence_id]
                    )
                )
            )
        async with get_session_factory().begin() as session:
            service = TraceImportService(SqlAlchemyEvidenceStore(session))
            first = await service.import_evidence(first_evidence)
            second = await service.import_evidence(second_evidence)
            first_again = await service.import_evidence(first_evidence)

        assert first.evidence_id != second.evidence_id
        assert first_again.status is ImportStatus.UNCHANGED

        async with get_session_factory()() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(TraceImport)
                .where(TraceImport.evidence_id.in_([first.evidence_id, second.evidence_id]))
            )
        assert count == 2
    finally:
        async with get_session_factory().begin() as session:
            await session.execute(
                delete(TraceImport).where(
                    TraceImport.evidence_id.in_(
                        [first_evidence.evidence_id, second_evidence.evidence_id]
                    )
                )
            )
