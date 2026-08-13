"""This module tests the baseline/candidate suite comparison for checkpoint 7.2.

A suite comparison runs every exact saved-case version against the baseline
and exactly one declared candidate change from equivalent approved state.
A passing candidate and a case-level regression produce distinct results;
hidden multi-variable changes, unsupported dimensions, baseline edits, and
missing required measurements are rejected or block a recommendation.
Model substitutes run only at the hosted-model boundary.
"""

import pytest
from pydantic_ai.models.function import FunctionModel

from app.adapters.pydantic_ai_agent import ModelConfig
from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.bundle.compiler import compile_bundle
from app.domain.comparison.compare import ComparisonVerdict
from app.domain.comparison.experiment import ConfigurationChangeType, ConfigurationVersions
from app.domain.regression.schemas import CaseSourceType
from app.domain.regression.service import RegressionCaseService
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.runner import RunVerdict, SimulationRun, run_bundle, state_from_bundle
from app.domain.simulation.scenarios import scenario_with_evidence
from app.domain.simulation.schemas import SimulationBudgets
from app.domain.suite.errors import InvalidSuiteError, SuiteRunError, UnsupportedChangeError
from app.domain.suite.runner import run_suite_comparison
from app.domain.suite.schemas import CaseSuite, SuiteMemberRef, SuiteVerdict
from tests.fakes.provisioner import stateful_provisioner_factory
from tests.fakes.regression_repository import InMemoryRegressionCaseRepository
from tests.fakes.scripted_model import (
    ScriptedPlan,
    build_scripted_model,
    escalate_plan,
    install_scripted_model,
    order_status_plan,
)

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

BASELINE_MODEL = ModelConfig(provider="openai", name="gpt-5.2")
CANDIDATE_MODEL = ModelConfig(provider="openai", name="gpt-5.3")


async def _bundle(scenario_id: str, **kwargs):
    source = FixtureTraceSource()
    trace_id = kwargs.pop("trace_id", scenario_id)
    evidence = await source.fetch_trace(trace_id)
    scenario = scenario_with_evidence(scenario_id, evidence)
    return compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **{**REVIEW, **kwargs},
    )


async def _saved_case(scenario_id: str, **kwargs):
    repository = InMemoryRegressionCaseRepository()
    service = RegressionCaseService(repository)
    saved = await service.save_case(
        bundle=await _bundle(scenario_id, **kwargs),
        source_type=CaseSourceType.INCIDENT,
    )
    case = await service.get_case(case_id=saved.case_id, case_version=saved.case_version)
    return case


def _suite(case, name: str = "suite-a") -> CaseSuite:
    return CaseSuite(
        suite_id=__import__("uuid").UUID(int=1),
        suite_version=1,
        name=name,
        members=(SuiteMemberRef(case_id=case.case_id, case_version=case.case_version),),
        created_at="2026-08-12T00:00:00Z",
    )


def _candidate_model(case, name: str = "gpt-5.3") -> ConfigurationVersions:
    """This function builds one candidate that changes only the model dimension."""
    return case.bundle.configuration_versions.model_copy(
        update={"model_provider": "openai", "model_name": name}
    )


def install_keyed_scripted_model(
    monkeypatch: pytest.MonkeyPatch,
    plans: dict[str, ScriptedPlan],
) -> None:
    """This function installs one deterministic model substitute per model name."""

    def build(config: object) -> FunctionModel:
        plan = plans.get(getattr(config, "name"))
        if plan is None:
            raise AssertionError(f"no scripted plan for model name {getattr(config, 'name')!r}")
        return build_scripted_model(plan)

    monkeypatch.setattr(
        "app.adapters.pydantic_ai_agent.build_pydantic_ai_model",
        build,
    )


def _measurementless_copy(run: SimulationRun) -> SimulationRun:
    """This function strips the measured tokens and cost from one run.

    The function-model substitute at the hosted-model boundary always
    reports its own token accounting, so the missing-measurement path is
    tested at the suite boundary with copies of one real completed run.
    """
    return run.model_copy(update={"cost_usd": None, "total_tokens": 0})


async def test_suite_comparison_passing_candidate_recommends_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _saved_case(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    state = case.bundle  # bundle state is identical for both sides
    install_keyed_scripted_model(
        monkeypatch,
        {
            "gpt-5.2": escalate_plan(),  # baseline fails the expected outcome
            "gpt-5.3": order_status_plan(state.scenario.request.customer_id),
        },
    )

    result = await run_suite_comparison(
        suite=_suite(case),
        cases=(case,),
        change_type=ConfigurationChangeType.MODEL,
        candidate=_candidate_model(case),
        provisioner_factory=stateful_provisioner_factory(),
        baseline_model_config=BASELINE_MODEL,
    )

    assert len(result.cases) == 1
    assert result.cases[0].comparison.verdict is ComparisonVerdict.CANDIDATE_PASSES
    assert result.totals.candidate_passes == 1
    assert result.totals.candidate_regresses == 0
    assert result.verdict is SuiteVerdict.RECOMMEND_CANDIDATE
    assert result.change_type is ConfigurationChangeType.MODEL
    assert result.baseline_label == "openai/gpt-5.2"
    assert result.candidate_label == "openai/gpt-5.3"
    assert result.cases[0].case_id == case.case_id
    assert result.cases[0].case_version == case.case_version
    assert result.cases[0].bundle_content_hash == case.bundle_content_hash
    assert result.cases[0].evidence_ref == case.evidence_ref


async def test_suite_comparison_regressing_candidate_keeps_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _saved_case(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    state = case.bundle
    install_keyed_scripted_model(
        monkeypatch,
        {
            "gpt-5.2": order_status_plan(state.scenario.request.customer_id),
            "gpt-5.3": escalate_plan(),  # candidate fails the expected outcome
        },
    )

    result = await run_suite_comparison(
        suite=_suite(case),
        cases=(case,),
        change_type=ConfigurationChangeType.MODEL,
        candidate=_candidate_model(case),
        provisioner_factory=stateful_provisioner_factory(),
        baseline_model_config=BASELINE_MODEL,
    )

    assert result.cases[0].comparison.verdict is ComparisonVerdict.CANDIDATE_REGRESSES
    assert result.totals.candidate_regresses == 1
    assert result.verdict is SuiteVerdict.KEEP_BASELINE


async def test_suite_comparison_no_material_difference_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _saved_case(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    state = case.bundle
    plan = order_status_plan(state.scenario.request.customer_id)
    install_keyed_scripted_model(monkeypatch, {"gpt-5.2": plan, "gpt-5.3": plan})

    result = await run_suite_comparison(
        suite=_suite(case),
        cases=(case,),
        change_type=ConfigurationChangeType.MODEL,
        candidate=_candidate_model(case),
        provisioner_factory=stateful_provisioner_factory(),
        baseline_model_config=BASELINE_MODEL,
    )

    assert result.cases[0].comparison.verdict is ComparisonVerdict.NO_MATERIAL_DIFFERENCE
    assert result.verdict is SuiteVerdict.INCONCLUSIVE


async def test_suite_comparison_rejects_hidden_multi_variable_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _saved_case(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    candidate = _candidate_model(case).model_copy(
        update={"answer_instructions_version": "a9"}
    )

    with pytest.raises(SuiteRunError, match="hidden change"):
        await run_suite_comparison(
            suite=_suite(case),
            cases=(case,),
            change_type=ConfigurationChangeType.MODEL,
            candidate=candidate,
            provisioner_factory=stateful_provisioner_factory(),
            baseline_model_config=BASELINE_MODEL,
        )


async def test_suite_comparison_rejects_identical_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _saved_case(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    identical = case.bundle.configuration_versions

    with pytest.raises(SuiteRunError, match="identical|no change"):
        await run_suite_comparison(
            suite=_suite(case),
            cases=(case,),
            change_type=ConfigurationChangeType.MODEL,
            candidate=identical,
            provisioner_factory=stateful_provisioner_factory(),
            baseline_model_config=BASELINE_MODEL,
        )


async def test_suite_comparison_rejects_baseline_that_does_not_match_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _saved_case(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )

    with pytest.raises(SuiteRunError, match="baseline model"):
        await run_suite_comparison(
            suite=_suite(case),
            cases=(case,),
            change_type=ConfigurationChangeType.MODEL,
            candidate=_candidate_model(case),
            provisioner_factory=stateful_provisioner_factory(),
            baseline_model_config=ModelConfig(provider="openai", name="other-model"),
        )


async def test_suite_comparison_rejects_unsupported_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = await _saved_case(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    candidate = _candidate_model(case).model_copy(
        update={"tool_versions": {"get_order_status": "2.0.0"}}
    )

    with pytest.raises(UnsupportedChangeError):
        await run_suite_comparison(
            suite=_suite(case),
            cases=(case,),
            change_type=ConfigurationChangeType.TOOLS,
            candidate=candidate,
            provisioner_factory=stateful_provisioner_factory(),
            baseline_model_config=BASELINE_MODEL,
        )


async def test_suite_comparison_rejects_case_set_mismatch() -> None:
    case = await _saved_case(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    other = await _saved_case("phase2-03-database-timeout")
    mismatched = CaseSuite(
        suite_id=__import__("uuid").UUID(int=2),
        suite_version=1,
        name="suite-b",
        members=(SuiteMemberRef(case_id=other.case_id, case_version=other.case_version),),
        created_at="2026-08-12T00:00:00Z",
    )

    with pytest.raises(InvalidSuiteError):
        await run_suite_comparison(
            suite=mismatched,
            cases=(case,),
            change_type=ConfigurationChangeType.MODEL,
            candidate=_candidate_model(case),
            provisioner_factory=stateful_provisioner_factory(),
            baseline_model_config=BASELINE_MODEL,
        )


async def test_suite_comparison_missing_measurements_block_recommendation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = FixtureTraceSource()
    evidence = await source.fetch_trace("phase2-08-model-cost-comparison-primary")
    scenario = scenario_with_evidence("phase2-08-model-cost-comparison", evidence)
    scenario = scenario.model_copy(
        update={
            "expected_behavior": scenario.expected_behavior.model_copy(
                update={
                    "budgets": SimulationBudgets(
                        performance_budget_ms=5000,
                        max_tokens=100,
                        max_cost_usd=1.0,
                    )
                }
            )
        }
    )
    repository = InMemoryRegressionCaseRepository()
    service = RegressionCaseService(repository)
    saved = await service.save_case(
        bundle=compile_bundle(
            scenario=scenario,
            evidence=evidence,
            coverage_items=COVERAGE_ITEMS,
            **REVIEW,
        ),
        source_type=CaseSourceType.INCIDENT,
    )
    case = await service.get_case(case_id=saved.case_id, case_version=saved.case_version)

    state = state_from_bundle(case.bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))
    completed_run = await run_bundle(
        bundle=case.bundle,
        provisioner_factory=stateful_provisioner_factory(),
        model_config=BASELINE_MODEL,
    )
    assert completed_run.verdict is RunVerdict.REPRODUCED

    async def measurementless_run(**kwargs: object) -> SimulationRun:
        return _measurementless_copy(completed_run)

    monkeypatch.setattr("app.domain.suite.runner.run_bundle", measurementless_run)

    result = await run_suite_comparison(
        suite=_suite(case, name="budget-suite"),
        cases=(case,),
        change_type=ConfigurationChangeType.MODEL,
        candidate=_candidate_model(case),
        provisioner_factory=stateful_provisioner_factory(),
        baseline_model_config=BASELINE_MODEL,
    )

    assert result.cases[0].comparison.verdict is ComparisonVerdict.INSUFFICIENT_EVIDENCE
    assert result.totals.missing_measurement_cases == 1
    assert result.verdict is SuiteVerdict.INCONCLUSIVE
    assert "missing" in result.verdict_reason
