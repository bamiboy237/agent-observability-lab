"""This module checks the LangSmith source against the real API.

If the environment lacks LangSmith credentials, the test runner skips it.
The test fetches one bounded cohort and validates the mapped evidence.
"""

import os

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.adapters.sources.langsmith import LangSmithSource, LangSmithSourceConfig
from app.config import Settings
from app.db import get_session_factory
from app.domain.evidence.models import TraceImport
from app.domain.evidence.service import ImportStatus, TraceImportService
from app.domain.evidence.source import TraceQuery
from app.domain.evidence.store import SqlAlchemyEvidenceStore

pytestmark = pytest.mark.skipif(
    not (os.environ.get("LANGSMITH_TRACING") == "true" and os.environ.get("LANGSMITH_API_KEY")),
    reason="LangSmith source check needs LANGSMITH_TRACING=true and LANGSMITH_API_KEY",
)


async def test_langsmith_source_fetches_bounded_cohort() -> None:
    assert os.environ.get("LANGSMITH_API_KEY") is not None
    config = LangSmithSourceConfig(
        api_key=SecretStr(os.environ["LANGSMITH_API_KEY"]),
        project=os.environ.get("LANGSMITH_PROJECT") or "simulate",
        scenario_id=os.environ.get("LANGSMITH_SCENARIO_ID"),
    )
    source = LangSmithSource(config)
    try:
        cohort = await source.fetch_traces(TraceQuery(limit=1))
    finally:
        await source.close()

    assert len(cohort) == 1
    evidence = cohort[0]
    assert evidence.source.platform == "langsmith"
    assert evidence.source.project == config.project
    assert evidence.events
    assert evidence.outcome.value in ("completed", "blocked", "escalated", "failed")
    assert evidence.source.url is not None
    print(
        f"LangSmith source ok: trace={evidence.source.trace_id} "
        f"outcome={evidence.outcome.value} reason={evidence.reason_code} "
        f"link={evidence.source.url}"
    )


async def test_langsmith_trace_imports_end_to_end_without_duplicates() -> None:
    from pydantic import ValidationError

    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for the end-to-end import check")
    if settings.environment != "test" or os.environ.get("RUN_DATABASE_TESTS") != "1":
        pytest.skip("set ENVIRONMENT=test and RUN_DATABASE_TESTS=1 for an isolated database")

    config = LangSmithSourceConfig(
        api_key=SecretStr(os.environ["LANGSMITH_API_KEY"]),
        project=os.environ.get("LANGSMITH_PROJECT") or "simulate",
    )
    source = LangSmithSource(config)
    try:
        cohort = await source.fetch_traces(TraceQuery(limit=1))
    finally:
        await source.close()
    assert len(cohort) == 1
    evidence = cohort[0]
    evidence_id = evidence.evidence_id

    try:
        async with get_session_factory().begin() as session:
            await session.execute(delete(TraceImport).where(TraceImport.evidence_id == evidence_id))
        async with get_session_factory().begin() as session:
            service = TraceImportService(SqlAlchemyEvidenceStore(session))
            first = await service.import_evidence(evidence)
            second = await service.import_evidence(evidence)

        assert first.status is ImportStatus.CREATED
        assert first.import_version == 1
        assert second.status is ImportStatus.UNCHANGED

        async with get_session_factory()() as session:
            rows = (
                (
                    await session.execute(
                        select(TraceImport).where(TraceImport.evidence_id == evidence_id)
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1
        assert rows[0].source_platform == "langsmith"
        assert rows[0].reason_code == evidence.reason_code
        print(
            f"LangSmith import ok: evidence={evidence_id} "
            f"outcome={rows[0].outcome} reason={rows[0].reason_code}"
        )
    finally:
        async with get_session_factory().begin() as session:
            await session.execute(delete(TraceImport).where(TraceImport.evidence_id == evidence_id))
