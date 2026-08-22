"""PostgreSQL proof for checkpoint 6.2 annotation revisions."""


import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import delete

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.adapters.sources.langsmith_feedback import FixtureLangSmithFeedbackSource
from app.config import Settings
from app.db import get_session_factory
from app.domain.failures.feedback import FeedbackImportService, SqlAlchemyFeedbackStore
from app.domain.failures.models import FeedbackAnnotationRecord
from app.domain.failures.schemas import FeedbackImportStatus


@pytest.fixture(scope="module", autouse=True)
def apply_failure_feedback_migrations() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for failure integration tests")
    command.upgrade(Config("alembic.ini"), "head")


@pytest.mark.integration
async def test_postgres_feedback_import_preserves_revisions() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-01-bad-prompt-policy-answer")
    raw = FixtureLangSmithFeedbackSource().annotations_for(evidence.source.trace_id)[0]
    annotation_id = raw["id"]
    async with get_session_factory().begin() as session:
        await session.execute(
            delete(FeedbackAnnotationRecord).where(
                FeedbackAnnotationRecord.annotation_id == annotation_id
            )
        )
    try:
        async with get_session_factory().begin() as session:
            service = FeedbackImportService(SqlAlchemyFeedbackStore(session))
            first = await service.import_annotation(raw, evidence)
            second = await service.import_annotation(raw, evidence)
            corrected = await service.import_annotation({**raw, "value": "routing"}, evidence)
        assert first.status is FeedbackImportStatus.CREATED
        assert second.status is FeedbackImportStatus.UNCHANGED
        assert corrected.status is FeedbackImportStatus.CORRECTED
        assert corrected.revision == 2
    finally:
        async with get_session_factory().begin() as session:
            await session.execute(
                delete(FeedbackAnnotationRecord).where(
                    FeedbackAnnotationRecord.annotation_id == annotation_id
                )
            )
