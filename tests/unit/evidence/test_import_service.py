"""This module tests provenance and idempotent storage for checkpoint 3.4.

Reimporting unchanged evidence does not duplicate it.
Changed evidence creates a visible new import version.
"""

import pytest
from tests.fakes.evidence_store import InMemoryEvidenceStore

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.evidence.errors import InvalidEvidence
from app.domain.evidence.models import stable_evidence_id
from app.domain.evidence.schemas import TraceEvidence, compute_content_hash
from app.domain.evidence.service import ImportStatus, TraceImportService


async def _evidence(trace_id: str) -> TraceEvidence:
    return await FixtureTraceSource().fetch_trace(trace_id)


async def test_import_creates_first_version() -> None:
    store = InMemoryEvidenceStore()
    service = TraceImportService(store)
    evidence = await _evidence("phase2-01-bad-prompt-policy-answer")

    result = await service.import_evidence(evidence)

    assert result.status is ImportStatus.CREATED
    assert result.import_version == 1
    assert result.content_hash == compute_content_hash(evidence)
    assert result.evidence_id == stable_evidence_id(evidence.source)
    assert result.source_platform == "langsmith"
    assert len(store.rows) == 1


async def test_reimporting_unchanged_evidence_does_not_duplicate() -> None:
    store = InMemoryEvidenceStore()
    service = TraceImportService(store)
    evidence = await _evidence("phase2-01-bad-prompt-policy-answer")

    first = await service.import_evidence(evidence)
    second = await service.import_evidence(evidence)

    assert first.status is ImportStatus.CREATED
    assert second.status is ImportStatus.UNCHANGED
    assert second.import_version == 1
    assert second.evidence_id == first.evidence_id
    assert len(store.rows) == 1


async def test_changed_evidence_creates_a_visible_new_version() -> None:
    store = InMemoryEvidenceStore()
    service = TraceImportService(store)
    evidence = await _evidence("phase2-01-bad-prompt-policy-answer")

    first = await service.import_evidence(evidence)
    changed = evidence.model_copy(update={"retry_count": evidence.retry_count + 1})
    second = await service.import_evidence(changed)

    assert first.status is ImportStatus.CREATED
    assert first.import_version == 1
    assert second.status is ImportStatus.UPDATED
    assert second.import_version == 2
    assert second.evidence_id == first.evidence_id
    assert second.content_hash != first.content_hash
    assert len(store.rows) == 2


async def test_importing_the_changed_version_twice_stays_idempotent() -> None:
    store = InMemoryEvidenceStore()
    service = TraceImportService(store)
    evidence = await _evidence("phase2-05-unconfirmed-refund")
    changed = evidence.model_copy(update={"retry_count": 2})

    await service.import_evidence(evidence)
    updated = await service.import_evidence(changed)
    repeated = await service.import_evidence(changed)

    assert updated.status is ImportStatus.UPDATED
    assert repeated.status is ImportStatus.UNCHANGED
    assert repeated.import_version == 2
    assert len(store.rows) == 2


async def test_distinct_traces_keep_distinct_evidence_ids() -> None:
    store = InMemoryEvidenceStore()
    service = TraceImportService(store)
    first = await service.import_evidence(await _evidence("phase2-01-bad-prompt-policy-answer"))
    second = await service.import_evidence(await _evidence("phase2-02-wrong-policy-evidence"))

    assert first.evidence_id != second.evidence_id
    assert first.import_version == second.import_version == 1
    assert len(store.rows) == 2


async def test_same_trace_id_in_different_projects_stays_distinct() -> None:
    store = InMemoryEvidenceStore()
    service = TraceImportService(store)
    first_evidence = await _evidence("phase2-01-bad-prompt-policy-answer")
    second_source = first_evidence.source.model_copy(update={"project": "another-project"})
    second_evidence = first_evidence.model_copy(
        update={
            "source": second_source,
            "evidence_id": stable_evidence_id(second_source),
        }
    )

    first = await service.import_evidence(first_evidence)
    second = await service.import_evidence(second_evidence)

    assert first.evidence_id != second.evidence_id
    assert len(store.rows) == 2


async def test_failed_insert_is_not_reported_as_saved() -> None:
    class RejectingStore(InMemoryEvidenceStore):
        async def save_import(self, *args: object, **kwargs: object) -> bool:
            return False

    service = TraceImportService(RejectingStore())

    with pytest.raises(InvalidEvidence, match="version conflicted"):
        await service.import_evidence(await _evidence("phase2-01-bad-prompt-policy-answer"))


async def test_stored_payload_preserves_full_evidence_json() -> None:
    store = InMemoryEvidenceStore()
    service = TraceImportService(store)
    evidence = await _evidence("phase2-03-database-timeout")

    await service.import_evidence(evidence)

    stored = store._saved_payloads[0][0]
    payload = store._saved_payloads[0][1]
    assert stored.source_project == "agent-reliability-lab"
    assert payload["source"]["platform"] == "langsmith"
    assert len(payload["events"]) == 8


async def test_evidence_id_is_consistent_with_source_identity() -> None:
    evidence = await _evidence("phase2-01-bad-prompt-policy-answer")
    assert evidence.evidence_id == stable_evidence_id(evidence.source)

    service = TraceImportService(InMemoryEvidenceStore())
    result = await service.import_evidence(evidence)
    assert result.evidence_id == stable_evidence_id(evidence.source) == evidence.evidence_id
