"""This module tests the saved regression case library for checkpoint 7.1.

An accepted bundle saves with a stable case id and an immutable version.
Saving the same bundle is deterministic. Saving changed content creates a
visible new version without overwriting history. Unreviewed or rejected
bundles cannot become cases. Cases can be listed, one exact version can be
retrieved, and a retrieved case runs through the existing runner.
"""

import pytest
from pydantic import ValidationError

from app.adapters.pydantic_ai_agent import ModelConfig
from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.bundle.compiler import compile_bundle
from app.domain.bundle.schemas import ReviewDecision, ReviewStatus
from app.domain.regression.errors import (
    CaseNotFoundError,
    InvalidCaseBundleError,
    ReviewRequiredError,
)
from app.domain.regression.repository import RegressionCaseRepository
from app.domain.regression.schemas import CaseSaveStatus, CaseSourceType, RegressionCase
from app.domain.regression.service import RegressionCaseService, stable_case_id
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.events import SimulationEventCollector
from app.domain.simulation.runner import (
    RunVerdict,
    run_bundle,
    scenario_from_bundle,
    state_from_bundle,
)
from app.domain.simulation.scenarios import scenario_with_evidence
from tests.fakes.provisioner import StatefulSupportProvisioner
from tests.fakes.regression_repository import InMemoryRegressionCaseRepository
from tests.fakes.scripted_model import install_scripted_model, order_status_plan

MODEL_CONFIG = ModelConfig(provider="openai", name="gpt-5.2")

COVERAGE_ITEMS = (
    CoverageItem(
        dependency="support.database",
        kind="stateful",
        tools=("get_order_status", "get_policy", "propose_refund", "confirm_refund", "escalate"),
        state_transitions=("order:delivered->refunded", "ticket:created"),
    ),
)

REVIEW = {
    "approved_request_message": "Use the approved synthetic request for this simulation.",
    "reviewer": "alice",
    "reviewed_at": "2026-08-08T00:00:00Z",
    "reason": "Reviewed and approved",
    "review_status": "approved",
}


async def _linked_scenario(scenario_id: str, trace_id: str | None = None):
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(trace_id or scenario_id)
    return scenario_with_evidence(scenario_id, evidence), evidence


async def _bundle(scenario_id: str, *, trace_id: str | None = None, **kwargs):
    scenario, evidence = await _linked_scenario(scenario_id, trace_id=trace_id)
    return compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **{**REVIEW, **kwargs},
    )


def _service() -> RegressionCaseService:
    repository: RegressionCaseRepository = InMemoryRegressionCaseRepository()
    return RegressionCaseService(repository)


async def test_save_accepted_bundle_creates_stable_immutable_version() -> None:
    bundle = await _bundle("phase2-03-database-timeout")
    service = _service()

    created = await service.save_case(bundle=bundle, source_type=CaseSourceType.INCIDENT)
    repeated = await service.save_case(bundle=bundle, source_type=CaseSourceType.INCIDENT)

    assert created.status is CaseSaveStatus.CREATED
    assert created.case_version == 1
    assert created.case_id == stable_case_id(
        "phase2-03-database-timeout", CaseSourceType.INCIDENT
    )
    assert created.bundle_content_hash == bundle.content_hash
    assert repeated.status is CaseSaveStatus.UNCHANGED
    assert repeated.case_id == created.case_id
    assert repeated.case_version == created.case_version


async def test_save_changed_bundle_creates_new_version_without_overwriting_history() -> None:
    service = _service()
    first_bundle = await _bundle("phase2-03-database-timeout")
    changed_bundle = await _bundle(
        "phase2-03-database-timeout",
        reason="Reviewed and approved after a second look",
    )
    assert changed_bundle.content_hash != first_bundle.content_hash

    created = await service.save_case(bundle=first_bundle, source_type=CaseSourceType.INCIDENT)
    updated = await service.save_case(bundle=changed_bundle, source_type=CaseSourceType.INCIDENT)

    assert updated.status is CaseSaveStatus.UPDATED
    assert updated.case_id == created.case_id
    assert updated.case_version == 2
    assert updated.bundle_content_hash == changed_bundle.content_hash

    first_case = await service.get_case(case_id=created.case_id, case_version=1)
    second_case = await service.get_case(case_id=created.case_id, case_version=2)
    assert first_case.bundle == first_bundle
    assert second_case.bundle == changed_bundle
    assert first_case.bundle_content_hash != second_case.bundle_content_hash


async def test_rejected_and_unreviewed_bundles_cannot_become_cases() -> None:
    bundle = await _bundle("phase2-03-database-timeout")
    rejected = bundle.model_copy(
        update={
            "review": ReviewDecision(
                status=ReviewStatus.REJECTED,
                reviewer="alice",
                reviewed_at="2026-08-08T00:00:00Z",
                reason="Rejected in review",
            )
        }
    )
    unreviewed = bundle.model_copy(
        update={
            "review": ReviewDecision(
                status=ReviewStatus.PENDING,
                reviewer="alice",
                reviewed_at="2026-08-08T00:00:00Z",
                reason="Not reviewed yet",
            )
        }
    )
    service = _service()

    with pytest.raises(ReviewRequiredError):
        await service.save_case(bundle=rejected, source_type=CaseSourceType.INCIDENT)
    with pytest.raises(ReviewRequiredError):
        await service.save_case(bundle=unreviewed, source_type=CaseSourceType.INCIDENT)

    assert await service.list_cases() == ()


async def test_bundle_with_tampered_content_hash_is_rejected() -> None:
    bundle = await _bundle("phase2-03-database-timeout")
    tampered = bundle.model_copy(update={"content_hash": "0" * 64})
    service = _service()

    with pytest.raises(InvalidCaseBundleError):
        await service.save_case(bundle=tampered, source_type=CaseSourceType.INCIDENT)

    assert await service.list_cases() == ()


async def test_source_type_is_limited_to_four_values() -> None:
    with pytest.raises(ValueError):
        CaseSourceType("custom")
    assert {item.value for item in CaseSourceType} == {
        "incident",
        "suspicious_success",
        "designed_edge_case",
        "model_comparison",
    }

    bundle = await _bundle("phase2-03-database-timeout")
    service = _service()
    for source_type in CaseSourceType:
        result = await service.save_case(bundle=bundle, source_type=source_type)
        assert result.status is CaseSaveStatus.CREATED


async def test_source_type_splits_cases_for_the_same_scenario() -> None:
    bundle = await _bundle("phase2-03-database-timeout")
    service = _service()

    incident = await service.save_case(bundle=bundle, source_type=CaseSourceType.INCIDENT)
    comparison = await service.save_case(
        bundle=bundle, source_type=CaseSourceType.MODEL_COMPARISON
    )

    assert incident.case_id != comparison.case_id
    assert incident.case_version == 1
    assert comparison.case_version == 1


async def test_list_cases_shows_latest_version_per_case() -> None:
    service = _service()
    first_bundle = await _bundle("phase2-03-database-timeout")
    changed_bundle = await _bundle("phase2-03-database-timeout", reason="Second review pass")
    other_bundle = await _bundle("phase2-05-unconfirmed-refund")
    await service.save_case(bundle=first_bundle, source_type=CaseSourceType.INCIDENT)
    await service.save_case(bundle=changed_bundle, source_type=CaseSourceType.INCIDENT)
    await service.save_case(bundle=other_bundle, source_type=CaseSourceType.SUSPICIOUS_SUCCESS)

    summaries = await service.list_cases()

    assert len(summaries) == 2
    by_scenario = {summary.scenario_id: summary for summary in summaries}
    assert by_scenario["phase2-03-database-timeout"].latest_version == 2
    assert (
        by_scenario["phase2-03-database-timeout"].latest_content_hash
        == changed_bundle.content_hash
    )
    assert by_scenario["phase2-03-database-timeout"].source_type is CaseSourceType.INCIDENT
    assert by_scenario["phase2-05-unconfirmed-refund"].latest_version == 1
    assert (
        by_scenario["phase2-05-unconfirmed-refund"].source_type
        is CaseSourceType.SUSPICIOUS_SUCCESS
    )


async def test_get_case_returns_exact_version_with_visible_provenance() -> None:
    bundle = await _bundle(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    service = _service()
    saved = await service.save_case(bundle=bundle, source_type=CaseSourceType.INCIDENT)

    case: RegressionCase = await service.get_case(
        case_id=saved.case_id, case_version=saved.case_version
    )

    assert case.case_id == saved.case_id
    assert case.case_version == 1
    assert case.source_type is CaseSourceType.INCIDENT
    assert case.scenario_id == "phase2-08-model-cost-comparison"
    assert case.bundle == bundle
    assert case.bundle_content_hash == bundle.content_hash
    assert case.evidence_ref == bundle.evidence_ref
    assert case.evidence_content_hash == bundle.evidence_content_hash
    assert case.configuration_versions == bundle.configuration_versions
    assert case.evidence_ref is not None
    assert case.evidence_ref.trace_id == "phase2-08-model-cost-comparison-primary"


async def test_get_missing_case_version_raises_not_found() -> None:
    bundle = await _bundle("phase2-03-database-timeout")
    service = _service()
    saved = await service.save_case(bundle=bundle, source_type=CaseSourceType.INCIDENT)

    with pytest.raises(CaseNotFoundError):
        await service.get_case(case_id=saved.case_id, case_version=99)
    with pytest.raises(CaseNotFoundError):
        await service.get_case(
            case_id=stable_case_id("missing-scenario", CaseSourceType.INCIDENT),
            case_version=1,
        )


async def test_retrieved_case_runs_through_the_existing_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    service = _service()
    saved = await service.save_case(bundle=bundle, source_type=CaseSourceType.INCIDENT)
    case = await service.get_case(case_id=saved.case_id, case_version=saved.case_version)

    state = state_from_bundle(case.bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))
    collector = SimulationEventCollector()
    provisioner = StatefulSupportProvisioner(
        scenario_from_bundle(case.bundle),
        event_sink=collector,
    )
    run = await run_bundle(
        bundle=case.bundle,
        provisioner_factory=lambda _request: provisioner,
        model_config=MODEL_CONFIG,
        collector=collector,
    )

    assert run.verdict is RunVerdict.REPRODUCED
    assert run.bundle_content_hash == case.bundle_content_hash
    assert run.evidence_ref == case.evidence_ref
    assert run.evidence_content_hash == case.evidence_content_hash
    assert provisioner.destroyed is True


async def test_regression_case_schema_rejects_provenance_mismatch() -> None:
    bundle = await _bundle("phase2-03-database-timeout")
    service = _service()
    saved = await service.save_case(bundle=bundle, source_type=CaseSourceType.INCIDENT)
    case = await service.get_case(case_id=saved.case_id, case_version=saved.case_version)

    with pytest.raises(ValidationError):
        RegressionCase(
            **case.model_dump(mode="json", exclude={"bundle_content_hash"}),
            bundle_content_hash="1" * 64,
        )
