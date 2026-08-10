"""This module tests the Model Lab cohort comparison (checkpoint 6.7).

The Model Lab holds prompt, retrieval, tools, workflow, routing, policy,
evaluators, fixtures, and starting state constant and changes only the hosted
model. Task success requires the expected business outcome AND every required
safety and state evaluator to pass; a candidate with a safety regression or
an unexpected state change is never recommended; runs without a typed
response are marked non-comparable with a clear reason.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.adapters.pydantic_ai_agent import ModelConfig
from app.domain.agent.schemas import ReasonCode, RouteIntent, SupportOutcome, SupportResponse
from app.domain.bundle.schemas import SimulationBundle
from app.domain.comparison.evaluators import EvaluatorReport
from app.domain.comparison.model_lab import (
    MIN_COMPARABLE_CASES,
    ModelLabTotals,
    ModelLabVerdict,
    _recommendation,
    run_model_lab,
)
from app.domain.simulation.provisioner import ProvisionerFactory
from app.domain.simulation.runner import RunVerdict, SimulationRun
from app.domain.simulation.schemas import ExpectedBehavior, SimulationState

BASELINE = ModelConfig(provider="openai", name="gpt-5.2")
CANDIDATE = ModelConfig(provider="openai", name="gpt-5.6-lite")

EVALUATOR_NAMES = (
    "authorization",
    "refund_confirmation",
    "allowed_tools",
    "state_transitions",
    "unexpected_state_changes",
    "policy_evidence",
    "output_schema",
    "escalation",
    "latency",
    "tokens",
    "cost",
)


def make_bundle() -> SimulationBundle:
    return SimulationBundle(
        scenario={
            "scenario_id": "phase2-99-test-case",
            "source_schema_version": "1.0.0",
            "source_content_hash": "1" * 64,
            "category": "answer_failure",
            "request": {
                "customer_id": str(uuid4()),
                "message": "Approved synthetic request for tests.",
            },
            "workflow_context": {
                "workflow": "support_agent",
                "workflow_version": "2.0.0",
            },
            "eligible_actions": ["get_order_status"],
            "required_dependency_coverage": [],
        },
        expected_behavior=ExpectedBehavior(
            outcome=SupportOutcome.COMPLETED,
            reason_codes=(ReasonCode.ORDER_STATUS_OK,),
        ),
        review={
            "status": "approved",
            "reviewer": "alice",
            "reviewed_at": "2026-08-08T00:00:00Z",
            "reason": "approved",
        },
    )


def make_run(
    *,
    verdict: RunVerdict = RunVerdict.REPRODUCED,
    outcome: SupportOutcome = SupportOutcome.COMPLETED,
    cost_usd: float | None = 0.01,
    total_latency_ms: float | None = 100.0,
    tokens: int = 100,
    retries: int = 0,
    tool_calls: tuple[str, ...] = ("get_order_status",),
    reason_code: ReasonCode = ReasonCode.ORDER_STATUS_OK,
    evaluator_failures: tuple[str, ...] = (),
) -> SimulationRun:
    report = EvaluatorReport(
        results=tuple(
            {
                "evaluator": name,
                "version": "1.0.0",
                "passed": name not in evaluator_failures,
                "reason": "ok" if name not in evaluator_failures else "failed check",
            }
            for name in EVALUATOR_NAMES
        )
    )
    run_response = (
        SupportResponse(
            intent=RouteIntent.ORDER_STATUS,
            outcome=outcome,
            reason_code=reason_code,
            message="Your order is shipped.",
            context={"routing": {"intent": "order_status", "confidence": 0.9}},
        )
        if verdict not in (RunVerdict.UNEXPECTED_ACCESS, RunVerdict.MISSING_COVERAGE)
        else None
    )
    return SimulationRun(
        run_id=uuid4(),
        bundle_id=UUID(int=1),
        bundle_content_hash="0" * 64,
        scenario_id="phase2-99-test-case",
        verdict=verdict,
        response=run_response,
        final_state=SimulationState(),
        evaluators=report,
        model_provider="openai",
        model_name="gpt-5.2",
        total_latency_ms=total_latency_ms,
        total_tokens=tokens,
        cost_usd=cost_usd,
        retries=retries,
        tool_calls=tool_calls,
        completed_at=datetime.now(UTC).isoformat(),
    )


def _stub_factory() -> ProvisionerFactory:
    raise AssertionError("run_model_lab must not provision environments in unit tests")


def test_recommendation_refuses_too_few_comparable_cases() -> None:
    verdict, reason = _recommendation(
        ModelLabTotals(comparable_cases=2),
        MIN_COMPARABLE_CASES,
    )
    assert verdict is ModelLabVerdict.INCONCLUSIVE
    assert "too few comparable completed cases" in reason


def test_recommendation_rejects_candidate_with_regressions() -> None:
    totals = ModelLabTotals(
        comparable_cases=4,
        regressions=1,
    )
    verdict, reason = _recommendation(totals, MIN_COMPARABLE_CASES)
    assert verdict is ModelLabVerdict.KEEP_BASELINE
    assert "regressed task success" in reason


def test_recommendation_keeps_baseline_for_expensive_equivalent_candidate() -> None:
    totals = __import__(
        "app.domain.comparison.model_lab", fromlist=["ModelLabTotals"]
    ).ModelLabTotals(
        comparable_cases=4,
        baseline=__import__(
            "app.domain.comparison.model_lab", fromlist=["ModelSideTotals"]
        ).ModelSideTotals(
            success_count=4, success_rate=1.0, total_cost=0.04, cost_per_successful_task=0.01
        ),
        candidate=__import__(
            "app.domain.comparison.model_lab", fromlist=["ModelSideTotals"]
        ).ModelSideTotals(
            success_count=4, success_rate=1.0, total_cost=0.12, cost_per_successful_task=0.03
        ),
    )
    verdict, reason = _recommendation(totals, MIN_COMPARABLE_CASES)
    assert verdict is ModelLabVerdict.KEEP_BASELINE
    assert "without a success gain" in reason


def test_recommendation_keeps_baseline_for_lower_quality_candidate() -> None:
    totals = __import__(
        "app.domain.comparison.model_lab", fromlist=["ModelLabTotals"]
    ).ModelLabTotals(
        comparable_cases=4,
        baseline=__import__(
            "app.domain.comparison.model_lab", fromlist=["ModelSideTotals"]
        ).ModelSideTotals(
            success_count=4, success_rate=1.0, total_cost=0.04, cost_per_successful_task=0.01
        ),
        candidate=__import__(
            "app.domain.comparison.model_lab", fromlist=["ModelSideTotals"]
        ).ModelSideTotals(
            success_count=2, success_rate=0.5, total_cost=0.03, cost_per_successful_task=0.015
        ),
    )
    verdict, _ = _recommendation(totals, MIN_COMPARABLE_CASES)
    assert verdict is ModelLabVerdict.KEEP_BASELINE


def test_recommendation_chooses_cheaper_equivalent_candidate() -> None:
    totals = __import__(
        "app.domain.comparison.model_lab", fromlist=["ModelLabTotals"]
    ).ModelLabTotals(
        comparable_cases=4,
        baseline=__import__(
            "app.domain.comparison.model_lab", fromlist=["ModelSideTotals"]
        ).ModelSideTotals(
            success_count=4, success_rate=1.0, total_cost=0.04, cost_per_successful_task=0.01
        ),
        candidate=__import__(
            "app.domain.comparison.model_lab", fromlist=["ModelSideTotals"]
        ).ModelSideTotals(
            success_count=4, success_rate=1.0, total_cost=0.02, cost_per_successful_task=0.005
        ),
    )
    verdict, _ = _recommendation(totals, MIN_COMPARABLE_CASES)
    assert verdict is ModelLabVerdict.RECOMMEND_CANDIDATE


def test_recommendation_is_inconclusive_when_models_are_equivalent() -> None:
    totals = __import__(
        "app.domain.comparison.model_lab", fromlist=["ModelLabTotals"]
    ).ModelLabTotals(
        comparable_cases=4,
        baseline=__import__(
            "app.domain.comparison.model_lab", fromlist=["ModelSideTotals"]
        ).ModelSideTotals(
            success_count=4, success_rate=1.0, total_cost=0.04, cost_per_successful_task=0.01
        ),
        candidate=__import__(
            "app.domain.comparison.model_lab", fromlist=["ModelSideTotals"]
        ).ModelSideTotals(
            success_count=4, success_rate=1.0, total_cost=0.04, cost_per_successful_task=0.01
        ),
    )
    verdict, _ = _recommendation(totals, MIN_COMPARABLE_CASES)
    assert verdict is ModelLabVerdict.INCONCLUSIVE


def test_empty_cohort_is_inconclusive() -> None:
    async def main() -> object:
        return await run_model_lab(
            bundles=(),
            baseline_model_config=BASELINE,
            candidate_model_config=CANDIDATE,
            provisioner_factory=_stub_factory,
        )

    result = asyncio.run(main())
    assert result.verdict is ModelLabVerdict.INCONCLUSIVE
    assert result.cohort == ()
    assert "empty" in result.verdict_reason


def test_cohort_is_explicitly_bounded() -> None:
    bundles = tuple(make_bundle() for _ in range(21))
    with pytest.raises(ValueError, match="explicitly bounded"):
        asyncio.run(
            run_model_lab(
                bundles=bundles,
                baseline_model_config=BASELINE,
                candidate_model_config=CANDIDATE,
                provisioner_factory=_stub_factory,
            )
        )


def test_case_outcome_records_policy_outcome() -> None:
    from app.domain.comparison.model_lab import _policy_outcome

    assert _policy_outcome(ReasonCode.POLICY_ANSWER) == "grounded"
    assert _policy_outcome(ReasonCode.POLICY_ANSWER_UNGROUNDED) == "ungrounded"
    assert _policy_outcome(ReasonCode.ORDER_STATUS_OK) is None


def test_recommendation_rejects_candidate_with_safety_regression() -> None:
    totals = ModelLabTotals(comparable_cases=4, safety_regressions=1)
    verdict, reason = _recommendation(totals, MIN_COMPARABLE_CASES)
    assert verdict is ModelLabVerdict.KEEP_BASELINE
    assert "safety" in reason


def test_recommendation_rejects_candidate_with_unexpected_state_changes() -> None:
    totals = ModelLabTotals(comparable_cases=4, unexpected_state_changes=1)
    verdict, reason = _recommendation(totals, MIN_COMPARABLE_CASES)
    assert verdict is ModelLabVerdict.KEEP_BASELINE
    assert "unexpected state changes" in reason


def _lab_with_scripted_runs(monkeypatch: pytest.MonkeyPatch) -> object:
    """This helper runs the lab loop against scripted run pairs."""
    import asyncio

    return asyncio.run(
        run_model_lab(
            bundles=(make_bundle(),),
            baseline_model_config=BASELINE,
            candidate_model_config=CANDIDATE,
            provisioner_factory=_stub_factory,
            min_comparable_cases=1,
        )
    )


def test_lab_requires_safety_evaluators_for_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_bundle(
        *,
        bundle: object,
        provisioner_factory: object,
        model_config: ModelConfig,
        evaluators: object = (),
    ) -> SimulationRun:
        if model_config.name == "gpt-5.2":
            return make_run()
        return make_run(evaluator_failures=("authorization",))

    monkeypatch.setattr("app.domain.comparison.model_lab.run_bundle", fake_run_bundle)
    result = _lab_with_scripted_runs(monkeypatch)

    assert result.totals.comparable_cases == 1
    assert result.totals.regressions == 1
    assert result.totals.safety_regressions == 1
    assert result.verdict is ModelLabVerdict.KEEP_BASELINE


def test_lab_never_recommends_unexpected_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_bundle(
        *,
        bundle: object,
        provisioner_factory: object,
        model_config: ModelConfig,
        evaluators: object = (),
    ) -> SimulationRun:
        if model_config.name == "gpt-5.2":
            return make_run()
        return make_run(evaluator_failures=("unexpected_state_changes",))

    monkeypatch.setattr("app.domain.comparison.model_lab.run_bundle", fake_run_bundle)
    result = _lab_with_scripted_runs(monkeypatch)

    assert result.totals.unexpected_state_changes == 1
    assert result.verdict is ModelLabVerdict.KEEP_BASELINE


def test_lab_requires_expected_outcome_for_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_bundle(
        *,
        bundle: object,
        provisioner_factory: object,
        model_config: ModelConfig,
        evaluators: object = (),
    ) -> SimulationRun:
        if model_config.name == "gpt-5.2":
            return make_run()
        return make_run(outcome=SupportOutcome.BLOCKED, reason_code=ReasonCode.ORDER_NOT_FOUND)

    monkeypatch.setattr("app.domain.comparison.model_lab.run_bundle", fake_run_bundle)
    result = _lab_with_scripted_runs(monkeypatch)

    assert result.cohort[0].baseline.task_success is True
    assert result.cohort[0].candidate.task_success is False
    assert result.totals.regressions == 1
    assert result.verdict is ModelLabVerdict.KEEP_BASELINE


def test_lab_marks_runs_without_response_non_comparable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_bundle(
        *,
        bundle: object,
        provisioner_factory: object,
        model_config: ModelConfig,
        evaluators: object = (),
    ) -> SimulationRun:
        if model_config.name == "gpt-5.2":
            return make_run()
        return make_run(verdict=RunVerdict.UNEXPECTED_ACCESS, outcome=SupportOutcome.FAILED)

    monkeypatch.setattr("app.domain.comparison.model_lab.run_bundle", fake_run_bundle)
    result = _lab_with_scripted_runs(monkeypatch)

    case = result.cohort[0]
    assert case.comparable is False
    assert case.baseline.verdict is RunVerdict.REPRODUCED
    assert case.candidate.verdict is RunVerdict.UNEXPECTED_ACCESS
    assert case.non_comparable_reason is not None
    assert "candidate" in case.non_comparable_reason
    assert result.totals.comparable_cases == 0
    assert result.verdict is ModelLabVerdict.INCONCLUSIVE
    assert "too few comparable" in result.verdict_reason
