"""This module tests the deterministic bundle compiler for checkpoint 5.5.

Compiling one reviewed trace or designed scenario produces a versioned
bundle. The same source and review input produce the same normalized content,
identifier, and hash. The compiler returns safe typed errors for missing
evidence, missing coverage, rejected reviews, forbidden data, and invalid
fixtures.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.agent.schemas import ReasonCode, SupportOutcome
from app.domain.bundle.compiler import compile_bundle, compile_confirmed_failure_bundle
from app.domain.bundle.errors import (
    ForbiddenDataError,
    MissingCoverageError,
    MissingEvidenceError,
    RejectedReviewError,
)
from app.domain.bundle.extract import synthetic_id
from app.domain.bundle.schemas import DependencyFixture, ReviewStatus
from app.domain.evidence.schemas import compute_content_hash
from app.domain.failures.schemas import (
    ConfirmedFailureGroup,
    FailureGroupReview,
    FailureKind,
    ReviewDecision,
)
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.scenarios import (
    CURRENT_POLICY,
    SCENARIO_BY_ID,
    STALE_POLICY,
    scenario_with_evidence,
)
from app.domain.simulation.schemas import (
    DependencyCoverageRequirement,
    ExpectedBehavior,
    ExpectedStateTransition,
    SimulationState,
)

COVERAGE_ITEMS = (
    CoverageItem(
        dependency="support.database",
        kind="stateful",
        tools=("get_order_status", "get_policy", "propose_refund", "confirm_refund", "escalate"),
        state_transitions=("order:delivered->refunded", "ticket:created"),
    ),
)

RECORDED_COVERAGE_ITEMS = (
    CoverageItem(
        dependency="support.database",
        kind="recorded",
        tools=("get_order_status",),
        state_transitions=(),
    ),
)

REVIEW = {
    "approved_request_message": "Use the approved synthetic request for this simulation.",
    "reviewer": "alice",
    "reviewed_at": "2026-08-08T00:00:00Z",
    "reason": "Reviewed and approved",
    "review_status": "approved",
}


async def _linked_scenario(scenario_id: str):
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(scenario_id)
    return scenario_with_evidence(scenario_id, evidence), evidence


def _with_recorded_order_lookup(scenario):
    return scenario.model_copy(
        update={
            "required_dependency_coverage": (
                DependencyCoverageRequirement(
                    dependency="support.database",
                    kind="recorded",
                    tools=("get_order_status",),
                ),
            )
        }
    )


async def test_compile_bundle_produces_stable_hash_for_identical_inputs() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")

    first = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )
    second = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )

    assert first.content_hash == second.content_hash
    assert first.bundle_id == second.bundle_id
    assert first.evidence_content_hash == compute_content_hash(evidence)
    assert first.scenario.source_content_hash == scenario.content_hash
    assert first.scenario.request.customer_id == synthetic_id(scenario.request.customer_id)
    assert first.scenario.request.message == REVIEW["approved_request_message"]
    assert first.expected_behavior == scenario.expected_behavior
    assert first.configuration_versions.workflow == "support_agent"
    assert first.configuration_versions.model_name == "gpt-5.2"
    assert first.review.status is ReviewStatus.APPROVED
    assert first.review.reviewer == "alice"


async def test_confirmed_failure_builder_requires_resolved_group_evidence() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    evidence_event = evidence.events[-1].event_id
    review = FailureGroupReview(
        review_id=uuid4(),
        proposal_id=uuid4(),
        decision=ReviewDecision.CONFIRM,
        reviewer="alice",
        reason="Confirmed from the linked timeout and retry evidence.",
        reviewed_at=datetime(2026, 8, 13, tzinfo=UTC),
        source_evidence_ids=(evidence.evidence_id,),
        evidence_event_ids={str(evidence.evidence_id): (evidence_event,)},
        algorithm_version="deterministic-dbscan-v1",
    )
    confirmed = ConfirmedFailureGroup(
        proposal_id=review.proposal_id,
        group_id=uuid4(),
        failure_kind=FailureKind.INFRASTRUCTURE,
        evidence_ids=(evidence.evidence_id,),
        evidence_event_ids={str(evidence.evidence_id): (evidence_event,)},
        review=review,
        dataset_id="failure_traces_v1",
        dataset_version=1,
        algorithm_version="deterministic-dbscan-v1",
    )

    bundle = compile_confirmed_failure_bundle(
        confirmed_failure=confirmed,
        scenario=scenario,
        evidence=evidence,
        approved_request_message=REVIEW["approved_request_message"],
        coverage_items=COVERAGE_ITEMS,
    )

    assert bundle.review.status is ReviewStatus.APPROVED
    assert bundle.review.source_evidence == f"failure-group:{confirmed.group_id}"

    wrong_group = confirmed.model_copy(update={"evidence_ids": (uuid4(),)})
    with pytest.raises(MissingEvidenceError):
        compile_confirmed_failure_bundle(
            confirmed_failure=wrong_group,
            scenario=scenario,
            evidence=evidence,
            approved_request_message=REVIEW["approved_request_message"],
            coverage_items=COVERAGE_ITEMS,
        )


async def test_compile_bundle_hash_changes_with_review_input() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")

    approved = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )
    other_reason = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        approved_request_message="Use the approved synthetic request for this simulation.",
        coverage_items=COVERAGE_ITEMS,
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed and approved after a second look",
        review_status="approved",
    )

    assert approved.content_hash != other_reason.content_hash


async def test_compile_bundle_rejects_missing_linked_evidence() -> None:
    scenario, _ = await _linked_scenario("phase2-01-bad-prompt-policy-answer")
    with pytest.raises(MissingEvidenceError) as excinfo:
        compile_bundle(
            scenario=scenario,
            evidence=None,
            approved_request_message="Use the approved synthetic policy request.",
            reviewer="alice",
            reviewed_at="2026-08-08T00:00:00Z",
            reason="Reviewed",
        )
    assert excinfo.value.code == "missing_evidence"


async def test_compile_bundle_accepts_approved_designed_scenario_without_evidence() -> None:
    scenario = SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"]

    bundle = compile_bundle(
        scenario=scenario,
        evidence=None,
        approved_request_message="Use the approved synthetic policy request.",
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed designed scenario",
        review_status="approved",
        coverage_items=(),
    )

    assert bundle.evidence_ref is None
    assert bundle.evidence_content_hash is None


async def test_compile_bundle_rejects_mismatched_evidence() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    mismatched = evidence.model_copy(update={"scenario_id": "phase2-01-bad-prompt-policy-answer"})
    with pytest.raises(MissingEvidenceError):
        compile_bundle(
            scenario=scenario,
            evidence=mismatched,
            approved_request_message="Use the approved synthetic order request.",
            reviewer="alice",
            reviewed_at="2026-08-08T00:00:00Z",
            reason="Reviewed",
            coverage_items=COVERAGE_ITEMS,
        )


async def test_compile_bundle_rejects_missing_coverage() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    with pytest.raises(MissingCoverageError) as excinfo:
        compile_bundle(
            scenario=scenario,
            evidence=evidence,
            approved_request_message="Use the approved synthetic order request.",
            reviewer="alice",
            reviewed_at="2026-08-08T00:00:00Z",
            reason="Reviewed",
            review_status="approved",
            coverage_items=(),
        )
    assert excinfo.value.code == "missing_simulation_coverage"


async def test_compile_bundle_rejects_unapproved_review_states() -> None:
    scenario, evidence = await _linked_scenario("phase2-01-bad-prompt-policy-answer")
    for state in ("pending", "rejected", "superseded"):
        with pytest.raises(RejectedReviewError) as excinfo:
            compile_bundle(
                scenario=scenario,
                evidence=evidence,
                approved_request_message="Use the approved synthetic policy request.",
                reviewer="alice",
                reviewed_at="2026-08-08T00:00:00Z",
                reason="Still reviewing",
                review_status=state,  # type: ignore[arg-type]
                coverage_items=COVERAGE_ITEMS,
            )
        assert excinfo.value.code == "review_not_approved"


async def test_compile_bundle_requires_explicit_approval() -> None:
    scenario, evidence = await _linked_scenario("phase2-01-bad-prompt-policy-answer")
    with pytest.raises(RejectedReviewError):
        compile_bundle(
            scenario=scenario,
            evidence=evidence,
            approved_request_message="Use the approved synthetic policy request.",
            reviewer="alice",
            reviewed_at="2026-08-08T00:00:00Z",
            reason="Reviewed",
            coverage_items=COVERAGE_ITEMS,
        )


async def test_compile_bundle_uses_reviewer_corrected_expectations() -> None:
    scenario, evidence = await _linked_scenario("phase2-01-bad-prompt-policy-answer")
    corrected = ExpectedBehavior(
        outcome=SupportOutcome.BLOCKED,
        reason_codes=(ReasonCode.POLICY_ANSWER_UNGROUNDED,),
        policy_grounded=False,
        note="Corrected by reviewer: keep blocked and require escalation.",
    )

    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        approved_request_message="Use the approved synthetic policy request.",
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewer corrected the expected note",
        review_status="approved",
        source_evidence=evidence.source.url,
        corrected_expected_behavior=corrected,
        coverage_items=COVERAGE_ITEMS,
    )

    assert (
        bundle.expected_behavior.note
        == "Corrected by reviewer: keep blocked and require escalation."
    )
    assert bundle.review.corrected_expected_behavior == corrected
    assert bundle.review.source_evidence == evidence.source.url


async def test_compile_bundle_rejects_forbidden_fixture_data() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    scenario = _with_recorded_order_lookup(scenario)
    fixture = DependencyFixture(
        dependency="support.database",
        adapter_name="support.database",
        adapter_version="4.0.0",
        tool="get_order_status",
        arguments={"order_id": str(synthetic_id(scenario.initial_state.orders[0].id))},
        payload={"id": "1", "api_key": "sk-secret"},
    )
    with pytest.raises(ForbiddenDataError) as excinfo:
        compile_bundle(
            scenario=scenario,
            evidence=evidence,
            approved_request_message="Use the approved synthetic order request.",
            reviewer="alice",
            reviewed_at="2026-08-08T00:00:00Z",
            reason="Reviewed",
            review_status="approved",
            coverage_items=RECORDED_COVERAGE_ITEMS,
            dependency_fixtures=(fixture,),
        )
    assert excinfo.value.code == "forbidden_data"


async def test_compile_bundle_records_redaction_decisions() -> None:
    scenario, evidence = await _linked_scenario("phase2-01-bad-prompt-policy-answer")
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        approved_request_message="Use the approved synthetic policy request.",
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed",
        review_status="approved",
        coverage_items=COVERAGE_ITEMS,
        redaction_decisions=[
            {
                "field": "customer.email",
                "reason": "Replaced with synthetic value to preserve relationships",
            }
        ],
    )
    assert bundle.redaction_decisions[0].field == "customer.email"
    assert any(decision.field == "policy.id" for decision in bundle.redaction_decisions)


async def test_compile_bundle_records_adapter_versions() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        approved_request_message="Use the approved synthetic order request.",
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed",
        review_status="approved",
        coverage_items=COVERAGE_ITEMS,
        adapter_versions={"support.database": "4.0.0", "order.lookup": "1.2.0"},
    )
    assert bundle.adapter_versions["support.database"] == "4.0.0"
    assert bundle.configuration_versions.tool_versions["get_order_status"] == "4.0.0"


async def test_compile_bundle_seeds_use_synthetic_identifiers() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        approved_request_message="Use the approved synthetic order request.",
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed",
        review_status="approved",
        coverage_items=COVERAGE_ITEMS,
    )

    bundle_dump = json.dumps(bundle.model_dump(mode="json"))
    real_order_id = str(scenario.initial_state.orders[0].id)
    assert real_order_id not in bundle_dump
    assert str(scenario.request.customer_id) not in bundle_dump
    assert scenario.request.message not in bundle_dump
    order_seed = next(seed for seed in bundle.resource_seeds if seed.resource == "order")
    assert order_seed.records[0]["id"] == str(synthetic_id(scenario.initial_state.orders[0].id))


async def test_compile_bundle_rejects_unapproved_source_request_text() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")

    with pytest.raises(ForbiddenDataError, match="forbidden content"):
        compile_bundle(
            scenario=scenario,
            evidence=evidence,
            approved_request_message=scenario.request.message,
            reviewer="alice",
            reviewed_at="2026-08-08T00:00:00Z",
            reason="Reviewed",
            review_status="approved",
            coverage_items=COVERAGE_ITEMS,
        )


async def test_compile_bundle_synthesizes_expected_transition_identifiers() -> None:
    scenario = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]
    transition = ExpectedStateTransition(
        resource="order",
        resource_id=scenario.initial_state.orders[0].id,
        from_status="delivered",
        to_status="refunded",
        reason_code="refund_executed",
    )
    scenario = scenario.model_copy(
        update={
            "expected_behavior": scenario.expected_behavior.model_copy(
                update={"state_transitions": (transition,)}
            )
        }
    )

    bundle = compile_bundle(
        scenario=scenario,
        evidence=None,
        approved_request_message="Refund the approved synthetic order after confirmation.",
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed",
        review_status="approved",
        coverage_items=COVERAGE_ITEMS,
    )

    stored = bundle.expected_behavior.state_transitions[0]
    assert stored.resource_id == synthetic_id(transition.resource_id)
    assert str(transition.resource_id) not in json.dumps(bundle.model_dump(mode="json"))


async def test_compile_bundle_rejects_fixture_echoing_scenario_message() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    scenario = _with_recorded_order_lookup(scenario)
    fixture = DependencyFixture(
        dependency="support.database",
        adapter_name="support.database",
        adapter_version="4.0.0",
        tool="get_order_status",
        arguments={"order_id": str(synthetic_id(scenario.initial_state.orders[0].id))},
        payload={"body": scenario.request.message},
    )
    with pytest.raises(ForbiddenDataError, match="forbidden content"):
        compile_bundle(
            scenario=scenario,
            evidence=evidence,
            approved_request_message="Use the approved synthetic order request.",
            reviewer="alice",
            reviewed_at="2026-08-08T00:00:00Z",
            reason="Reviewed",
            review_status="approved",
            coverage_items=RECORDED_COVERAGE_ITEMS,
            dependency_fixtures=(fixture,),
        )


async def test_compile_bundle_records_policy_version_only_when_unambiguous() -> None:
    scenario, evidence = await _linked_scenario("phase2-01-bad-prompt-policy-answer")
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        approved_request_message="Use the approved synthetic policy request.",
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed",
        review_status="approved",
        coverage_items=COVERAGE_ITEMS,
    )
    assert bundle.configuration_versions.policy_version == "2026-07-30"

    multi_policy = scenario.model_copy(
        update={"initial_state": SimulationState(policies=(CURRENT_POLICY, STALE_POLICY))}
    )
    ambiguous = compile_bundle(
        scenario=multi_policy,
        evidence=evidence,
        approved_request_message="Use the approved synthetic policy request.",
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed",
        review_status="approved",
        coverage_items=COVERAGE_ITEMS,
    )
    assert ambiguous.configuration_versions.policy_version is None


async def test_compile_bundle_round_trips_through_json() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        approved_request_message="Use the approved synthetic order request.",
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed",
        review_status="approved",
        coverage_items=COVERAGE_ITEMS,
    )
    restored = type(bundle).model_validate(bundle.model_dump(mode="json"))
    assert restored == bundle
    assert restored.bundle_id == bundle.bundle_id
    assert restored.content_hash == bundle.content_hash
