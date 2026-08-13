"""This module implements the deterministic bundle compiler.

The compiler links every derived field to source evidence, scenario state, or
reviewer approval. It returns safe typed errors for missing evidence, missing
coverage, rejected reviews, forbidden data, and invalid fixtures. Compiling
the same evidence, scenario, and review always produces the same normalized
content, identifier, and hash.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from app.domain.bundle.allowlist import (
    scan_bundle_content,
    validate_fault_script,
    validate_safe_text,
)
from app.domain.bundle.errors import MissingCoverageError, MissingEvidenceError, RejectedReviewError
from app.domain.bundle.extract import (
    extract_dependency_fixtures,
    extract_resource_seeds,
    redaction_decisions_for_seeds,
    synthetic_id,
)
from app.domain.bundle.schemas import (
    BundleRequest,
    BundleScenario,
    ConfigurationVersions,
    CoverageInfo,
    DependencyFixture,
    RedactionDecision,
    ReviewDecision,
    ReviewStatus,
    SimulationBundle,
)
from app.domain.evidence.schemas import TraceEvidence, compute_content_hash
from app.domain.failures.schemas import ConfirmedFailureGroup
from app.domain.simulation.adapters import CoverageItem, requirement_is_covered
from app.domain.simulation.faults import FaultScript
from app.domain.simulation.schemas import (
    ExpectedBehavior,
    ExpectedStateTransition,
    SimulationScenario,
    compute_scenario_hash,
)

ReviewState = Literal["pending", "approved", "rejected", "superseded"]

_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)


def _compile_review(
    scenario: SimulationScenario,
    *,
    status: ReviewState,
    reviewer: str,
    reviewed_at: str,
    reason: str,
    source_evidence: str | None,
    corrected_expected_behavior: ExpectedBehavior | None,
) -> ReviewDecision:
    """This function builds one review decision, rejecting unapproved states."""
    if status != "approved":
        raise RejectedReviewError(scenario_id=scenario.scenario_id, state=status)
    return ReviewDecision(
        status=ReviewStatus.APPROVED,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        reason=reason,
        source_evidence=source_evidence,
        corrected_expected_behavior=corrected_expected_behavior,
    )


def _compile_coverage(
    scenario: SimulationScenario,
    *,
    coverage_items: Sequence[CoverageItem],
) -> CoverageInfo:
    """This function computes the coverage of one scenario and returns its report.

    Missing requirements are reported instead of silently compiling.
    """
    missing = tuple(
        requirement.dependency
        for requirement in scenario.required_dependency_coverage
        if not requirement_is_covered(requirement, coverage_items)
    )
    if missing:
        raise MissingCoverageError(scenario_id=scenario.scenario_id, missing=missing)
    covered = tuple(sorted({item.dependency for item in coverage_items if item.dependency}))
    return CoverageInfo(covered=covered, missing=())


def _compile_tool_versions(
    coverage_items: Sequence[CoverageItem],
    adapter_versions: Mapping[str, str],
) -> dict[str, str]:
    """This function derives tool versions from the adapters that serve them."""
    tool_versions: dict[str, str] = {}
    for item in coverage_items:
        version = adapter_versions.get(item.dependency)
        if version is None:
            continue
        for tool in item.tools:
            tool_versions[tool] = version
    return dict(sorted(tool_versions.items()))


def _private_source_values(scenario: SimulationScenario) -> tuple[str, ...]:
    """Return source values that a portable bundle must not repeat."""
    identifiers = {str(scenario.request.customer_id)}
    identifiers.update(str(order.id) for order in scenario.initial_state.orders)
    identifiers.update(str(order.customer_id) for order in scenario.initial_state.orders)
    identifiers.update(str(ticket.id) for ticket in scenario.initial_state.tickets)
    identifiers.update(str(ticket.customer_id) for ticket in scenario.initial_state.tickets)
    identifiers.update(
        str(ticket.order_id)
        for ticket in scenario.initial_state.tickets
        if ticket.order_id is not None
    )
    identifiers.update(str(policy.id) for policy in scenario.initial_state.policies)
    identifiers.update(_UUID_PATTERN.findall(scenario.request.message))
    return (scenario.request.message, scenario.title, *sorted(identifiers))


def _safe_expected_behavior(expected: ExpectedBehavior) -> ExpectedBehavior:
    """Replace identifiers in expected transitions with stable synthetic values."""
    transitions = tuple(
        ExpectedStateTransition(
            resource=transition.resource,
            resource_id=(
                synthetic_id(transition.resource_id)
                if transition.resource_id is not None
                else None
            ),
            any_resource_id=transition.any_resource_id,
            from_status=transition.from_status,
            to_status=transition.to_status,
            reason_code=transition.reason_code,
        )
        for transition in expected.state_transitions
    )
    permitted = tuple(
        ExpectedStateTransition(
            resource=transition.resource,
            resource_id=(
                synthetic_id(transition.resource_id)
                if transition.resource_id is not None
                else None
            ),
            any_resource_id=transition.any_resource_id,
            from_status=transition.from_status,
            to_status=transition.to_status,
            reason_code=transition.reason_code,
        )
        for transition in expected.permitted_state_transitions
    )
    return expected.model_copy(
        update={
            "state_transitions": transitions,
            "permitted_state_transitions": permitted,
        }
    )


def _safe_scenario(
    scenario: SimulationScenario,
    *,
    approved_request_message: str,
) -> BundleScenario:
    """Build the portable scenario projection from reviewer-approved input."""
    return BundleScenario(
        scenario_id=scenario.scenario_id,
        source_schema_version=scenario.schema_version,
        source_content_hash=scenario.content_hash or compute_scenario_hash(scenario),
        category=scenario.category,
        request=BundleRequest(
            customer_id=synthetic_id(scenario.request.customer_id),
            message=approved_request_message,
            refund_confirmed=scenario.request.refund_confirmed,
        ),
        workflow_context=scenario.workflow_context,
        eligible_actions=scenario.eligible_actions,
        required_dependency_coverage=scenario.required_dependency_coverage,
    )


def compile_bundle(
    *,
    scenario: SimulationScenario,
    evidence: TraceEvidence | None = None,
    approved_request_message: str,
    reviewer: str,
    reviewed_at: str,
    reason: str,
    review_status: ReviewState = "pending",
    source_evidence: str | None = None,
    corrected_expected_behavior: ExpectedBehavior | None = None,
    dependency_fixtures: Sequence[DependencyFixture] | None = None,
    fault_script: FaultScript | None = None,
    adapter_versions: Mapping[str, str] | None = None,
    redaction_decisions: Sequence[RedactionDecision] | None = None,
    coverage_items: Sequence[CoverageItem] = (),
    forbidden_substrings: Sequence[str] = (),
) -> SimulationBundle:
    """This function compiles one reviewed scenario into a portable bundle.

    The same inputs always produce the same normalized content, identifier,
    and hash. The function fails closed with safe typed errors when evidence
    is missing, coverage is missing, the review is not approved, data is
    forbidden, or a fixture is invalid.
    """
    if evidence is None and scenario.evidence_ref is not None:
        raise MissingEvidenceError(scenario_id=scenario.scenario_id)
    if (
        evidence is not None
        and evidence.scenario_id is not None
        and evidence.scenario_id != scenario.scenario_id
    ):
        raise MissingEvidenceError(
            scenario_id=scenario.scenario_id,
            detail=f"evidence belongs to scenario {evidence.scenario_id!r}",
        )
    if (
        evidence is not None
        and scenario.evidence_ref is not None
        and scenario.evidence_ref.trace_id != evidence.source.trace_id
    ):
        raise MissingEvidenceError(
            scenario_id=scenario.scenario_id,
            detail=(
                f"scenario links trace {scenario.evidence_ref.trace_id!r}, "
                f"not {evidence.source.trace_id!r}"
            ),
        )

    private_source_values = _private_source_values(scenario)
    validate_safe_text(
        approved_request_message,
        context="approved simulation request",
        forbidden_substrings=private_source_values,
    )

    source_expected = (
        corrected_expected_behavior
        if corrected_expected_behavior is not None
        else scenario.expected_behavior
    )
    expected = _safe_expected_behavior(source_expected)
    reviewed = _compile_review(
        scenario,
        status=review_status,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        reason=reason,
        source_evidence=source_evidence,
        corrected_expected_behavior=(expected if corrected_expected_behavior is not None else None),
    )
    coverage = _compile_coverage(scenario, coverage_items=coverage_items)
    versions = dict(adapter_versions or {})

    seeds = extract_resource_seeds(scenario.initial_state)
    fixtures = extract_dependency_fixtures(
        scenario,
        dependency_fixtures=tuple(dependency_fixtures) if dependency_fixtures is not None else (),
    )

    declared_tools = tuple(
        sorted(
            {
                tool
                for requirement in scenario.required_dependency_coverage
                for tool in requirement.tools
            }
        )
    )
    validate_fault_script(
        fault_script,
        allowed_tools=declared_tools,
        allowed_dependencies=tuple(
            requirement.dependency for requirement in scenario.required_dependency_coverage
        ),
        forbidden_substrings=tuple(forbidden_substrings) + private_source_values,
    )

    scan_bundle_content(
        resources={seed.resource: [dict(record) for record in seed.records] for seed in seeds},
        fixtures=[fixture.model_dump(mode="json") for fixture in fixtures],
        forbidden_substrings=tuple(forbidden_substrings) + private_source_values,
    )

    all_redactions = (
        tuple(redaction_decisions or ())
        + (
            RedactionDecision(
                field="scenario.request.customer_id",
                reason="Replaced with a stable synthetic value",
            ),
            RedactionDecision(
                field="scenario.request.message",
                reason="Replaced with reviewer-approved simulation text",
            ),
        )
        + redaction_decisions_for_seeds(seeds)
    )

    policy_versions = {policy.version for policy in scenario.initial_state.policies}
    return SimulationBundle(
        scenario=_safe_scenario(
            scenario,
            approved_request_message=approved_request_message,
        ),
        evidence_ref=evidence.source if evidence is not None else None,
        evidence_content_hash=(compute_content_hash(evidence) if evidence is not None else None),
        expected_behavior=expected,
        configuration_versions=ConfigurationVersions(
            workflow=scenario.workflow_context.workflow,
            workflow_version=scenario.workflow_context.workflow_version,
            routing_instructions_version=scenario.workflow_context.routing_instructions_version,
            answer_instructions_version=scenario.workflow_context.answer_instructions_version,
            model_provider=scenario.workflow_context.model_provider,
            model_name=scenario.workflow_context.model_name,
            policy_version=(next(iter(policy_versions)) if len(policy_versions) == 1 else None),
            tool_versions=_compile_tool_versions(coverage_items, versions),
            configuration_version=scenario.workflow_context.workflow_version,
        ),
        resource_seeds=seeds,
        dependency_fixtures=fixtures,
        fault_script=fault_script,
        adapter_versions=versions,
        coverage=coverage,
        redaction_decisions=all_redactions,
        review=reviewed,
    )


def compile_confirmed_failure_bundle(
    *,
    confirmed_failure: ConfirmedFailureGroup,
    scenario: SimulationScenario,
    evidence: TraceEvidence,
    approved_request_message: str,
    corrected_expected_behavior: ExpectedBehavior | None = None,
    dependency_fixtures: Sequence[DependencyFixture] | None = None,
    fault_script: FaultScript | None = None,
    adapter_versions: Mapping[str, str] | None = None,
    redaction_decisions: Sequence[RedactionDecision] | None = None,
    coverage_items: Sequence[CoverageItem] = (),
    forbidden_substrings: Sequence[str] = (),
) -> SimulationBundle:
    """Compile an incident-derived bundle from a human-confirmed group only."""
    if evidence.evidence_id not in confirmed_failure.evidence_ids:
        raise MissingEvidenceError(
            scenario_id=scenario.scenario_id,
            detail="the confirmed failure group does not include this evidence",
        )
    expected_event_ids = set(
        confirmed_failure.evidence_event_ids.get(str(evidence.evidence_id), ())
    )
    actual_event_ids = {event.event_id for event in evidence.events}
    if not expected_event_ids or not expected_event_ids <= actual_event_ids:
        raise MissingEvidenceError(
            scenario_id=scenario.scenario_id,
            detail="confirmed failure evidence events do not resolve in the source trace",
        )
    review = confirmed_failure.review
    return compile_bundle(
        scenario=scenario,
        evidence=evidence,
        approved_request_message=approved_request_message,
        reviewer=review.reviewer,
        reviewed_at=review.reviewed_at.isoformat(),
        reason=review.reason,
        review_status="approved",
        source_evidence=f"failure-group:{confirmed_failure.group_id}",
        corrected_expected_behavior=corrected_expected_behavior,
        dependency_fixtures=dependency_fixtures,
        fault_script=fault_script,
        adapter_versions=adapter_versions,
        redaction_decisions=redaction_decisions,
        coverage_items=coverage_items,
        forbidden_substrings=forbidden_substrings,
    )
