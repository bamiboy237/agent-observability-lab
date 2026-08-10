"""This module tests the SimulationScenario schema for checkpoint 4.1.

All eight Phase 2 scenarios validate against one versioned schema.
Expected behavior stays separate from the original production output.
A scenario may be designed from fixed local data or linked to evidence.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.agent.scenarios import SCENARIOS as PHASE2_SCENARIOS
from app.domain.agent.schemas import ReasonCode, SupportOutcome
from app.domain.simulation.scenarios import (
    DELIVERED_ORDER,
    SCENARIO_BY_ID,
    SCENARIOS,
    scenario_with_evidence,
)
from app.domain.simulation.schemas import (
    ExpectedStateTransition,
    SimulationScenario,
    compute_scenario_hash,
    link_evidence,
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.scenario_id for s in SCENARIOS])
async def test_all_eight_scenarios_validate_and_round_trip(scenario: SimulationScenario) -> None:
    dumped = scenario.model_dump(mode="json")
    restored = SimulationScenario.model_validate(dumped)
    assert restored == scenario
    assert restored.schema_version == "1.0.0"
    assert restored.content_hash == scenario.content_hash


def test_simulation_scenarios_match_phase_two_definitions() -> None:
    assert [s.scenario_id for s in SCENARIOS] == [s.scenario_id for s in PHASE2_SCENARIOS]
    assert len(SCENARIO_BY_ID) == 8


def test_every_scenario_declares_workflow_context_and_actions() -> None:
    for scenario in SCENARIOS:
        assert scenario.workflow_context.workflow == "support_agent"
        assert scenario.workflow_context.workflow_version == "2.0.0"
        assert scenario.eligible_actions
        assert scenario.expected_behavior.reason_codes


def test_scenario_03_and_06_declare_retry_budget() -> None:
    assert (
        SCENARIO_BY_ID["phase2-03-database-timeout"].expected_behavior.budgets.performance_budget_ms
        == 5000
    )
    assert (
        SCENARIO_BY_ID["phase2-06-repeated-step"].expected_behavior.budgets.performance_budget_ms
        == 5000
    )


def test_scenario_07_declares_tight_latency_budget() -> None:
    scenario = SCENARIO_BY_ID["phase2-07-slow-database"]
    assert scenario.expected_behavior.budgets.performance_budget_ms == 1000
    assert scenario.expected_behavior.outcome is SupportOutcome.COMPLETED
    assert ReasonCode.OK_SLOW in scenario.expected_behavior.reason_codes


def test_expected_behavior_is_separate_from_original_output() -> None:
    scenario = SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"]
    assert scenario.original_production_behavior is not None
    original = scenario.original_production_behavior
    corrected = original.model_copy(update={"reason_code": ReasonCode.ORDER_STATUS_OK})
    assert corrected.reason_code is ReasonCode.ORDER_STATUS_OK
    assert scenario.expected_behavior.reason_codes == (ReasonCode.POLICY_ANSWER_UNGROUNDED,)
    assert scenario.expected_behavior.outcome is SupportOutcome.BLOCKED


def test_scenario_05_requires_stateful_refund_coverage() -> None:
    scenario = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]
    kinds = {
        requirement.dependency: requirement.kind
        for requirement in scenario.required_dependency_coverage
    }
    assert kinds["support.database"] == "stateful"
    assert "confirm_refund" in scenario.eligible_actions


async def test_scenario_links_to_trace_evidence() -> None:
    source = FixtureTraceSource()
    evidence = await source.fetch_trace("phase2-01-bad-prompt-policy-answer")
    linked = scenario_with_evidence("phase2-01-bad-prompt-policy-answer", evidence)

    assert linked.evidence_ref is not None
    assert linked.evidence_ref.platform == "langsmith"
    assert linked.evidence_ref.trace_id == "phase2-01-bad-prompt-policy-answer"
    assert linked.content_hash != SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"].content_hash
    assert (
        linked.expected_behavior
        == SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"].expected_behavior
    )


async def test_evidence_link_rejects_scenario_mismatch() -> None:
    source = FixtureTraceSource()
    evidence = await source.fetch_trace("phase2-02-wrong-policy-evidence")
    with pytest.raises(ValueError, match="belongs to scenario"):
        scenario_with_evidence("phase2-01-bad-prompt-policy-answer", evidence)


async def test_link_evidence_keeps_expected_behavior() -> None:
    scenario = SCENARIO_BY_ID["phase2-03-database-timeout"]
    linked = link_evidence(
        scenario,
        platform="langsmith",
        trace_id="trace-abc",
        project="agent-replay",
        url="https://smith.langchain.com/traces/trace-abc",
    )
    assert linked.evidence_ref is not None
    assert linked.evidence_ref.trace_id == "trace-abc"
    assert linked.expected_behavior == scenario.expected_behavior


def test_unknown_top_level_field_is_rejected() -> None:
    payload = SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"].model_dump(mode="json")
    payload["vendor_secret_store"] = "do-not-copy"
    with pytest.raises(ValidationError, match="vendor_secret_store"):
        SimulationScenario.model_validate(payload)


def test_duplicate_eligible_actions_are_rejected() -> None:
    payload = SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"].model_dump(mode="json")
    payload["eligible_actions"] = ["get_policy", "get_policy"]
    with pytest.raises(ValidationError, match="must not repeat"):
        SimulationScenario.model_validate(payload)


def test_designed_scenario_can_declare_expected_state_transition() -> None:
    scenario = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]
    designed = scenario.model_copy(
        update={
            "expected_behavior": scenario.expected_behavior.model_copy(
                update={
                    "state_transitions": (
                        ExpectedStateTransition(
                            resource="order",
                            resource_id=DELIVERED_ORDER,
                            from_status="delivered",
                            to_status="refunded",
                            reason_code="refund_executed",
                        ),
                    )
                }
            ),
            "content_hash": None,
        }
    )
    designed.content_hash = compute_scenario_hash(designed)
    dumped = designed.model_dump(mode="json")
    restored = SimulationScenario.model_validate(dumped)
    assert restored.expected_behavior.state_transitions[0].reason_code == "refund_executed"
    assert restored.expected_behavior.state_transitions[0].to_status == "refunded"


def test_transition_resource_id_wildcard_is_explicit_and_exclusive() -> None:
    wildcard = ExpectedStateTransition(
        resource="ticket",
        any_resource_id=True,
        to_status="created",
        reason_code="ticket_created",
    )
    assert wildcard.resource_id is None

    with pytest.raises(ValidationError, match="cannot also declare"):
        ExpectedStateTransition(
            resource="ticket",
            resource_id=uuid4(),
            any_resource_id=True,
            to_status="created",
            reason_code="ticket_created",
        )
    with pytest.raises(ValidationError, match="must declare a resource id"):
        ExpectedStateTransition(
            resource="ticket",
            to_status="created",
            reason_code="ticket_created",
        )
    with pytest.raises(ValidationError, match="only for a newly created ticket"):
        ExpectedStateTransition(
            resource="order",
            any_resource_id=True,
            from_status="delivered",
            to_status="refunded",
            reason_code="refund_executed",
        )


def test_dynamic_ticket_permissions_use_stable_explicit_wildcards() -> None:
    for scenario_id in (
        "phase2-04-wrong-tool-arguments",
        "phase2-05-unconfirmed-refund",
    ):
        scenario = SCENARIO_BY_ID[scenario_id]
        ticket = next(
            transition
            for transition in scenario.expected_behavior.permitted_state_transitions
            if transition.resource == "ticket"
        )
        assert ticket.any_resource_id is True
        assert ticket.resource_id is None


def test_content_hash_is_stable_and_content_sensitive() -> None:
    scenario = SCENARIO_BY_ID["phase2-04-wrong-tool-arguments"]
    first = compute_scenario_hash(scenario)
    second = compute_scenario_hash(scenario)
    assert first == second
    assert len(first) == 64

    changed = scenario.model_copy(update={"title": "Changed title"})
    assert compute_scenario_hash(changed) != first


def test_scenario_02_declares_stale_policy_in_initial_state() -> None:
    scenario = SCENARIO_BY_ID["phase2-02-wrong-policy-evidence"]
    assert [policy.version for policy in scenario.initial_state.policies] == ["2025-01-01"]
    requirement = scenario.required_dependency_coverage[0]
    assert requirement.dependency == "support.database"
    assert requirement.kind == "stateful"
    assert "get_policy" in requirement.tools
