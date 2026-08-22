"""This module tests the saved case library against PostgreSQL for checkpoint 7.1.

An accepted bundle saves with a stable case id and an immutable version.
Re-saving the same bundle is a no-op. Changed content creates a visible new
version without overwriting history. Unreviewed or rejected bundles cannot
become cases. Cases can be listed, one exact version can be retrieved, and a
retrieved case runs through the existing runner.
Tests run only against the configured isolated database.
"""


import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import delete

from app.adapters.pydantic_ai_agent import ModelConfig
from app.adapters.sources.fixture_source import FixtureTraceSource
from app.config import Settings
from app.db import get_session_factory
from app.domain.bundle.compiler import compile_bundle
from app.domain.bundle.schemas import ReviewDecision, ReviewStatus
from app.domain.regression.errors import ReviewRequiredError
from app.domain.regression.models import RegressionCaseRecord
from app.domain.regression.repository import SqlAlchemyRegressionCaseRepository
from app.domain.regression.schemas import CaseSaveStatus, CaseSourceType
from app.domain.regression.service import RegressionCaseService
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


@pytest.fixture(scope="module", autouse=True)
def apply_regression_migrations() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for regression case integration tests")
    command.upgrade(Config("alembic.ini"), "head")


@pytest.mark.integration
async def test_postgres_saves_lists_versions_and_runs_one_saved_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_bundle = await _bundle(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    changed_bundle = await _bundle(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
        reason="Reviewed and approved after a second look",
    )
    assert changed_bundle.content_hash != first_bundle.content_hash

    created = None
    try:
        async with get_session_factory().begin() as session:
            service = RegressionCaseService(SqlAlchemyRegressionCaseRepository(session))
            created = await service.save_case(
                bundle=first_bundle, source_type=CaseSourceType.INCIDENT
            )
            repeated = await service.save_case(
                bundle=first_bundle, source_type=CaseSourceType.INCIDENT
            )
            updated = await service.save_case(
                bundle=changed_bundle, source_type=CaseSourceType.INCIDENT
            )
            summaries = await service.list_cases()

        assert created.status is CaseSaveStatus.CREATED
        assert created.case_version == 1
        assert repeated.status is CaseSaveStatus.UNCHANGED
        assert repeated.case_version == 1
        assert updated.status is CaseSaveStatus.UPDATED
        assert updated.case_id == created.case_id
        assert updated.case_version == 2
        assert len(summaries) == 1
        assert summaries[0].case_id == created.case_id
        assert summaries[0].latest_version == 2
        assert summaries[0].latest_content_hash == changed_bundle.content_hash
        assert summaries[0].source_type is CaseSourceType.INCIDENT

        async with get_session_factory().begin() as session:
            service = RegressionCaseService(SqlAlchemyRegressionCaseRepository(session))
            first_case = await service.get_case(case_id=created.case_id, case_version=1)
            second_case = await service.get_case(case_id=created.case_id, case_version=2)

        assert first_case.bundle == first_bundle
        assert second_case.bundle == changed_bundle
        assert first_case.bundle_content_hash == first_bundle.content_hash
        assert second_case.bundle_content_hash == changed_bundle.content_hash
        assert first_case.evidence_ref == first_bundle.evidence_ref
        assert first_case.evidence_content_hash == first_bundle.evidence_content_hash
        assert first_case.configuration_versions == first_bundle.configuration_versions
        assert second_case.evidence_ref is not None
        assert second_case.evidence_ref.url is not None

        state = state_from_bundle(second_case.bundle)
        install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))
        collector = SimulationEventCollector()
        provisioner = StatefulSupportProvisioner(
            scenario_from_bundle(second_case.bundle),
            event_sink=collector,
        )
        run = await run_bundle(
            bundle=second_case.bundle,
            provisioner_factory=lambda _request: provisioner,
            model_config=MODEL_CONFIG,
            collector=collector,
        )

        assert run.verdict is RunVerdict.REPRODUCED
        assert run.bundle_content_hash == second_case.bundle_content_hash
        assert run.evidence_ref == second_case.evidence_ref
        assert provisioner.destroyed is True

        rejected = first_bundle.model_copy(
            update={
                "review": ReviewDecision(
                    status=ReviewStatus.REJECTED,
                    reviewer="alice",
                    reviewed_at="2026-08-08T00:00:00Z",
                    reason="Rejected in review",
                )
            }
        )
        async with get_session_factory().begin() as session:
            service = RegressionCaseService(SqlAlchemyRegressionCaseRepository(session))
            with pytest.raises(ReviewRequiredError):
                await service.save_case(
                    bundle=rejected, source_type=CaseSourceType.SUSPICIOUS_SUCCESS
                )
    finally:
        if created is not None:
            async with get_session_factory().begin() as session:
                await session.execute(
                    delete(RegressionCaseRecord).where(
                        RegressionCaseRecord.case_id == created.case_id
                    )
                )
