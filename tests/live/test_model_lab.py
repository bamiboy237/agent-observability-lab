"""This module runs one live baseline-versus-candidate model comparison.

The check uses ``MODEL_PROVIDER``/``MODEL_NAME`` as the baseline and
``MODEL_CANDIDATE_PROVIDER``/``MODEL_CANDIDATE_NAME`` as the candidate. If
the environment lacks the second model configuration, the test skips.
"""

import pytest

from app.adapters.pydantic_ai_agent import ModelConfig
from app.adapters.sources.fixture_source import FixtureTraceSource
from app.config import Settings
from app.db import get_session_factory
from app.domain.bundle.compiler import compile_bundle
from app.domain.bundle.extract import synthetic_id
from app.domain.comparison.model_lab import ModelLabVerdict, run_model_lab
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.provisioner import postgres_provisioner_factory
from app.domain.simulation.scenarios import scenario_with_evidence
from tests.live.conftest import build_live_settings

COVERAGE_ITEMS = (
    CoverageItem(
        dependency="support.database",
        kind="stateful",
        tools=("get_order_status", "get_policy", "propose_refund", "confirm_refund", "escalate"),
        state_transitions=("order:delivered->refunded", "ticket:created"),
    ),
)


@pytest.fixture(scope="module")
def live_lab_settings() -> Settings:
    settings = build_live_settings()
    if settings is None or not settings.candidate_model_configured:
        pytest.skip(
            "The live Model Lab check needs MODEL_PROVIDER, MODEL_NAME, "
            "MODEL_CANDIDATE_PROVIDER, and MODEL_CANDIDATE_NAME (plus API keys "
            "for hosted endpoints); set them to run this check."
        )
    return settings


@pytest.fixture(scope="module")
def live_lab_models(live_lab_settings: Settings) -> tuple[ModelConfig, ModelConfig]:
    provider = live_lab_settings.model_provider
    name = live_lab_settings.model_name
    candidate_provider = live_lab_settings.model_candidate_provider
    candidate_name = live_lab_settings.model_candidate_name
    assert provider is not None and name is not None
    assert candidate_provider is not None and candidate_name is not None
    return (
        ModelConfig(
            provider=provider,
            name=name,
            base_url=live_lab_settings.model_base_url,
            api_key=live_lab_settings.model_api_key,
        ),
        ModelConfig(
            provider=candidate_provider,
            name=candidate_name,
            base_url=live_lab_settings.model_candidate_base_url,
            api_key=live_lab_settings.model_candidate_api_key,
        ),
    )


async def test_live_model_lab_compares_baseline_and_candidate(
    live_lab_models: tuple[ModelConfig, ModelConfig],
) -> None:
    baseline_model, candidate_model = live_lab_models
    scenario_id = "phase2-08-model-cost-comparison"
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(f"{scenario_id}-primary")
    scenario = scenario_with_evidence(scenario_id, evidence)
    synthetic_order = synthetic_id(scenario.initial_state.orders[0].id)
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        approved_request_message=(
            f"What is the status of order {synthetic_order}? I want to know where "
            "it is and when it will arrive."
        ),
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed and approved",
        review_status="approved",
    )

    result = await run_model_lab(
        bundles=(bundle,),
        baseline_model_config=baseline_model,
        candidate_model_config=candidate_model,
        provisioner_factory=postgres_provisioner_factory(
            lambda: get_session_factory()(),
            isolation_confirmed=True,
        ),
        min_comparable_cases=1,
    )

    assert len(result.cohort) == 1
    case = result.cohort[0]
    assert case.baseline.verdict.value in ("reproduced", "accepted", "failed")
    assert case.candidate.verdict.value in ("reproduced", "accepted", "failed")
    assert result.totals.comparable_cases in (0, 1)
    assert result.verdict in (
        ModelLabVerdict.RECOMMEND_CANDIDATE,
        ModelLabVerdict.KEEP_BASELINE,
        ModelLabVerdict.INCONCLUSIVE,
    )
