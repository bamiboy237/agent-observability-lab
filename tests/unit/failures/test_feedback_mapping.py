"""Checkpoint 6.2 tests for provenance-preserving feedback import."""

import pytest

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.adapters.sources.langsmith_feedback import FixtureLangSmithFeedbackSource
from app.domain.failures.feedback import (
    FeedbackImportService,
    InMemoryFeedbackStore,
    MalformedFeedback,
    UnknownFeedbackReference,
)
from app.domain.failures.schemas import FeedbackImportStatus


@pytest.mark.asyncio
async def test_feedback_import_is_idempotent_and_correctable() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-01-bad-prompt-policy-answer")
    raw = FixtureLangSmithFeedbackSource().annotations_for(evidence.source.trace_id)[0]
    store = InMemoryFeedbackStore()
    service = FeedbackImportService(store)

    created = await service.import_annotation(raw, evidence)
    unchanged = await service.import_annotation(raw, evidence)
    corrected_raw = {**raw, "value": "routing"}
    corrected = await service.import_annotation(corrected_raw, evidence)

    assert created.status is FeedbackImportStatus.CREATED
    assert unchanged.status is FeedbackImportStatus.UNCHANGED
    assert corrected.status is FeedbackImportStatus.CORRECTED
    assert corrected.revision == 2
    assert len(store.rows) == 2
    assert store.rows[0].label == "policy"
    assert store.rows[1].label == "routing"


@pytest.mark.asyncio
async def test_feedback_rejects_unknown_references_and_keeps_optional_fields_optional() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-01-bad-prompt-policy-answer")
    service = FeedbackImportService(InMemoryFeedbackStore())
    raw = {
        "id": "annotation-unknown",
        "trace_id": evidence.source.trace_id,
        "event_id": "missing-event",
        "value": "policy",
        "score": "not-a-number",
        "created_at": "not-a-date",
    }
    with pytest.raises(UnknownFeedbackReference):
        await service.import_annotation(raw, evidence)
    malformed = {"id": "annotation-malformed", "trace_id": evidence.source.trace_id}
    with pytest.raises(MalformedFeedback):
        await service.import_annotation(malformed, evidence)
