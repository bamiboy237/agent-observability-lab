"""This module tests LangSmith run mapping against the eight Phase 2 fixtures.

Every scenario fixture maps into validated TraceEvidence with its expected
outcome and evidence. Private data never appears in the mapped evidence.
Invalid fixtures fail with useful errors.
"""

import pytest

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.agent.scenarios import SCENARIO_BY_ID
from app.domain.evidence.errors import InvalidEvidence, UnsupportedTrace
from app.domain.evidence.schemas import TraceEventKind, TraceEvidence

EXPECTED_OUTCOMES = {
    "phase2-01-bad-prompt-policy-answer": ("blocked", "policy_answer_ungrounded"),
    "phase2-02-wrong-policy-evidence": ("completed", "policy_answer"),
    "phase2-03-database-timeout": ("completed", "ok_with_retry"),
    "phase2-04-wrong-tool-arguments": ("completed", "order_not_found"),
    "phase2-05-unconfirmed-refund": ("blocked", "refund_blocked_unconfirmed"),
    "phase2-06-repeated-step": ("completed", "ok_with_retry"),
    "phase2-07-slow-database": ("completed", "ok_slow"),
    "phase2-08-model-cost-comparison-primary": ("completed", "order_status_ok"),
    "phase2-08-model-cost-comparison-candidate": ("completed", "order_status_ok"),
}

PRIVATE_FRAGMENTS = (
    "alex.rivera@example.test",
    "samira.patel@example.test",
    "return a delivered order",
    "refund my order",
    "CONFIRMATION_TOKEN",
    "135.00",
    "48.25",
)


def _all_attributes(evidence: TraceEvidence) -> dict[str, object]:
    attributes: dict[str, object] = {}
    for event in evidence.events:
        attributes.update(event.attributes)
    return attributes


@pytest.mark.parametrize("trace_id", sorted(EXPECTED_OUTCOMES))
async def test_scenario_fixture_maps_to_valid_evidence(trace_id: str) -> None:
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(trace_id)

    assert evidence.schema_version == "3.0.0"
    assert evidence.source.platform == "langsmith"
    assert evidence.source.project == "agent-reliability-lab"
    assert evidence.source.trace_id == trace_id
    assert evidence.source.url.startswith("https://smith.langchain.com/projects/p/")
    assert "?trace=" in evidence.source.url
    assert evidence.scenario_id in SCENARIO_BY_ID

    outcome, reason = EXPECTED_OUTCOMES[trace_id]
    assert evidence.outcome.value == outcome
    assert evidence.reason_code == reason

    scenario = SCENARIO_BY_ID[evidence.scenario_id]
    attributes = _all_attributes(evidence)
    for required in scenario.required_trace_evidence:
        assert required in attributes, f"{trace_id} missing evidence {required}"


@pytest.mark.parametrize("trace_id", sorted(EXPECTED_OUTCOMES))
async def test_scenario_fixture_contains_no_private_data(trace_id: str) -> None:
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(trace_id)
    serialized = evidence.model_dump_json()
    for fragment in PRIVATE_FRAGMENTS:
        assert fragment not in serialized, f"{trace_id} leaked {fragment!r}"


async def test_scenario_01_records_bad_instructions_and_grounding() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-01-bad-prompt-policy-answer")
    attributes = _all_attributes(evidence)
    assert attributes["agent.answer.instructions.version"] == "0-bad"
    assert attributes["support.policy.grounded"] is False
    assert evidence.outcome.value == "blocked"
    assert evidence.reason_code == "policy_answer_ungrounded"
    assert not any(event.kind is TraceEventKind.TOOL for event in evidence.events), (
        "the grounding check must not see a get_policy tool call"
    )


async def test_scenario_02_records_wrong_policy_version() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-02-wrong-policy-evidence")
    attributes = _all_attributes(evidence)
    assert attributes["retrieval.source"] == "policy_documents"
    assert attributes["retrieval.policy.version"] == "2025-01-01"
    assert attributes["support.policy.grounded"] is False
    assert evidence.timing.retrieval_latency_ms == pytest.approx(120.5)


async def test_scenario_03_records_retry_and_timeout() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-03-database-timeout")
    attributes = _all_attributes(evidence)
    assert evidence.retry_count == 1
    assert attributes["tool.error.code"] == "timeout"
    assert evidence.timing.budget_ms == 5000
    retry_events = [e for e in evidence.events if e.kind is TraceEventKind.RETRY]
    assert len(retry_events) == 1
    assert any(call.error_code == "timeout" for call in evidence.dependency_calls)


async def test_scenario_04_records_tool_failure_without_inventing_data() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-04-wrong-tool-arguments")
    attributes = _all_attributes(evidence)
    assert attributes["tool.error.code"] == "order_not_found"
    assert attributes["db.error.code"] == "order_not_found"
    assert evidence.reason_code == "order_not_found"


async def test_scenario_05_records_unconfirmed_refund() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-05-unconfirmed-refund")
    assert evidence.confirmation is not None
    assert evidence.confirmation.required is True
    assert evidence.confirmation.verified is False
    assert evidence.reason_code == "refund_blocked_unconfirmed"
    decisions = evidence.policy_decisions
    assert len(decisions) == 1
    assert decisions[0].decision == "allowed"
    assert decisions[0].version == "2026-07-30"


async def test_scenario_06_records_repeated_step() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-06-repeated-step")
    assert evidence.retry_count == 1
    assert evidence.reason_code == "ok_with_retry"
    tool_events = [e for e in evidence.events if e.kind is TraceEventKind.TOOL]
    assert len(tool_events) == 2
    assert len({e.name for e in tool_events}) == 1


async def test_scenario_07_records_latency_above_budget() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-07-slow-database")
    attributes = _all_attributes(evidence)
    assert float(attributes["db.latency.ms"]) >= 2000  # type: ignore[arg-type]
    assert evidence.timing.budget_ms == 1000
    assert evidence.timing.total_latency_ms is not None
    assert evidence.timing.total_latency_ms >= float(attributes["db.latency.ms"])  # type: ignore[arg-type]
    assert evidence.reason_code == "ok_slow"


async def test_scenario_08_primary_and_candidate_are_equivalent_and_distinct() -> None:
    source = FixtureTraceSource()
    primary = await source.fetch_trace("phase2-08-model-cost-comparison-primary")
    candidate = await source.fetch_trace("phase2-08-model-cost-comparison-candidate")
    assert primary.reason_code == candidate.reason_code == "order_status_ok"
    assert primary.model is not None and candidate.model is not None
    assert primary.model.name == "gpt-5.2"
    assert candidate.model.name == "gpt-4.1-mini"
    assert primary.tokens.cost_usd is not None
    assert candidate.tokens.cost_usd is not None
    assert candidate.tokens.cost_usd < primary.tokens.cost_usd


async def test_unknown_sensitive_fixture_is_rejected_with_field_name() -> None:
    with pytest.raises(UnsupportedTrace, match="user.message"):
        await FixtureTraceSource().fetch_trace("invalid-unknown-sensitive")


async def test_broken_parent_fixture_is_rejected_with_parent_id() -> None:
    with pytest.raises(UnsupportedTrace, match="unknown parent"):
        await FixtureTraceSource().fetch_trace("invalid-broken-parent")


async def test_out_of_order_fixture_is_rejected() -> None:
    with pytest.raises(InvalidEvidence, match="starts before its parent"):
        await FixtureTraceSource().fetch_trace("invalid-out-of-order")


async def test_harmless_vendor_keys_are_dropped_and_recorded() -> None:
    evidence = await FixtureTraceSource().fetch_trace("phase2-01-bad-prompt-policy-answer")
    assert "ls_provider" in evidence.redaction.dropped_keys
    assert set(evidence.task_input) == {
        "agent.workflow.version",
        "agent.routing.instructions.version",
        "agent.answer.instructions.version",
        "support.intent",
        "support.confidence",
        "support.message.length",
    }
