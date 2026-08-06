"""This module tests the TraceEvidence schema for checkpoint 3.1.

The schema rejects unknown fields, broken event order, invalid parent
references, and non-allowlisted attributes.
"""

import pytest
from pydantic import ValidationError

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.evidence.schemas import (
    TraceEvent,
    TraceEventKind,
    TraceEvidence,
    compute_content_hash,
    summarize_evidence,
)


@pytest.fixture
async def sample_evidence() -> TraceEvidence:
    source = FixtureTraceSource()
    return await source.fetch_trace("phase2-01-bad-prompt-policy-answer")


async def test_fixture_evidence_round_trips_through_json(sample_evidence: TraceEvidence) -> None:
    dumped = sample_evidence.model_dump(mode="json")
    restored = TraceEvidence.model_validate(dumped)
    assert restored == sample_evidence
    assert restored.schema_version == "3.0.0"


async def test_unknown_top_level_field_is_rejected(sample_evidence: TraceEvidence) -> None:
    payload = sample_evidence.model_dump(mode="json")
    payload["vendor_secret_store"] = "do-not-copy"
    with pytest.raises(ValidationError, match="vendor_secret_store"):
        TraceEvidence.model_validate(payload)


async def test_unknown_event_field_is_rejected(sample_evidence: TraceEvidence) -> None:
    payload = sample_evidence.model_dump(mode="json")
    payload["events"][0]["free_text"] = "unrestricted"
    with pytest.raises(ValidationError, match="free_text"):
        TraceEvidence.model_validate(payload)


async def test_non_allowlisted_attribute_is_rejected(sample_evidence: TraceEvidence) -> None:
    payload = sample_evidence.model_dump(mode="json")
    payload["events"][0]["attributes"]["user.message"] = "leak"
    with pytest.raises(ValidationError, match="user.message"):
        TraceEvidence.model_validate(payload)


@pytest.mark.parametrize("field_name", ["task_input", "task_output"])
async def test_non_allowlisted_task_field_is_rejected(
    sample_evidence: TraceEvidence,
    field_name: str,
) -> None:
    payload = sample_evidence.model_dump(mode="json")
    payload[field_name]["api_key"] = "secret"
    with pytest.raises(ValidationError, match="api_key"):
        TraceEvidence.model_validate(payload)


async def test_duplicate_event_ids_are_rejected(sample_evidence: TraceEvidence) -> None:
    payload = sample_evidence.model_dump(mode="json")
    payload["events"][1]["event_id"] = payload["events"][0]["event_id"]
    with pytest.raises(ValidationError, match="duplicate event id"):
        TraceEvidence.model_validate(payload)


async def test_multiple_roots_are_rejected(sample_evidence: TraceEvidence) -> None:
    payload = sample_evidence.model_dump(mode="json")
    payload["events"][1]["parent_id"] = None
    with pytest.raises(ValidationError, match="exactly one root"):
        TraceEvidence.model_validate(payload)


async def test_unknown_parent_reference_is_rejected(sample_evidence: TraceEvidence) -> None:
    payload = sample_evidence.model_dump(mode="json")
    payload["events"][1]["parent_id"] = "does-not-exist"
    with pytest.raises(ValidationError, match="unknown parent"):
        TraceEvidence.model_validate(payload)


async def test_child_before_parent_order_is_rejected(sample_evidence: TraceEvidence) -> None:
    payload = sample_evidence.model_dump(mode="json")
    child = payload["events"][1]
    child["start_time"] = "2026-08-04T09:59:59.000Z"
    with pytest.raises(ValidationError, match="starts before its parent"):
        TraceEvidence.model_validate(payload)


async def test_end_before_start_is_rejected(sample_evidence: TraceEvidence) -> None:
    payload = sample_evidence.model_dump(mode="json")
    payload["events"][0]["end_time"] = "2026-08-04T09:00:00.000Z"
    with pytest.raises(ValidationError, match="ends before it starts"):
        TraceEvidence.model_validate(payload)


def test_empty_event_list_is_rejected() -> None:
    payload = {
        "evidence_id": "6444a178-2cd9-4e4a-8b0e-4e2a1f2e3d4c",
        "source": {
            "platform": "langsmith",
            "project": "agent-reliability-lab",
            "trace_id": "t-1",
        },
        "outcome": "completed",
        "reason_code": "order_status_ok",
        "events": [],
    }
    with pytest.raises(ValidationError, match="at least 1 item"):
        TraceEvidence.model_validate(payload)


async def test_content_hash_is_stable_and_content_sensitive(
    sample_evidence: TraceEvidence,
) -> None:
    first = compute_content_hash(sample_evidence)
    second = compute_content_hash(sample_evidence)
    assert first == second
    assert len(first) == 64

    changed = sample_evidence.model_copy(update={"retry_count": sample_evidence.retry_count + 1})
    assert compute_content_hash(changed) != first


async def test_summarize_evidence_reduces_core_contract(
    sample_evidence: TraceEvidence,
) -> None:
    summary = summarize_evidence(sample_evidence)
    assert summary.platform == "langsmith"
    assert summary.outcome.value == "blocked"
    assert summary.reason_code == "policy_answer_ungrounded"
    assert summary.tokens_total == 596
    assert summary.tool_names == ()


def test_event_kind_enum_uses_canonical_names() -> None:
    assert TraceEventKind.TURN.value == "turn"
    assert TraceEventKind.TOOL.value == "tool"
    assert TraceEventKind.POLICY.value == "policy"


def test_event_error_code_requires_stable_pattern() -> None:
    with pytest.raises(ValidationError, match="error_code"):
        TraceEvent(
            event_id="e1",
            kind=TraceEventKind.TOOL,
            name="support_agent.tool.get_order_status",
            parent_id=None,
            start_time="2026-08-04T10:00:00Z",
            error_code="error with spaces and secrets",
            attributes={},
        )
