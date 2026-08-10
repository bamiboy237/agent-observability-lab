"""This module tests the evidence-linked comparison (checkpoint 6.6).

A comparison runs the same bundle with the baseline and candidate and returns
``candidate_passes``, ``candidate_regresses``, ``no_material_difference``, or
``insufficient_evidence``. Any safety regression or missing required
measurement blocks ``candidate_passes``, and every result links to the bundle
and its source evidence.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.agent.schemas import ReasonCode, RouteIntent, SupportOutcome, SupportResponse
from app.domain.bundle.schemas import SimulationBundle
from app.domain.comparison.compare import (
    ComparisonVerdict,
    compare_runs,
)
from app.domain.comparison.evaluators import EvaluatorReport
from app.domain.simulation.runner import RunVerdict, SimulationRun
from app.domain.simulation.schemas import ExpectedBehavior, SimulationBudgets, SimulationState


def make_run(
    *,
    verdict: RunVerdict = RunVerdict.REPRODUCED,
    outcome: SupportOutcome = SupportOutcome.COMPLETED,
    reason_code: ReasonCode = ReasonCode.ORDER_STATUS_OK,
    tool_calls: tuple[str, ...] = ("get_order_status",),
    retries: int = 0,
    total_latency_ms: float | None = 100.0,
    cost_usd: float | None = 0.01,
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
            for name in (
                "authorization",
                "refund_confirmation",
                "allowed_tools",
                "state_transitions",
                "policy_evidence",
                "output_schema",
                "escalation",
                "latency",
                "tokens",
                "cost",
            )
        )
    )
    return SimulationRun(
        run_id=uuid4(),
        bundle_id=UUID(int=1),
        bundle_content_hash="0" * 64,
        scenario_id="phase2-99-test-case",
        verdict=verdict,
        response=SupportResponse(
            intent=RouteIntent.ORDER_STATUS,
            outcome=outcome,
            reason_code=reason_code,
            message="Your order is shipped.",
            context={"routing": {"intent": "order_status", "confidence": 0.9}},
        ),
        final_state=SimulationState(),
        evaluators=report,
        model_provider="openai",
        model_name="gpt-5.2",
        total_latency_ms=total_latency_ms,
        total_tokens=120,
        cost_usd=cost_usd,
        retries=retries,
        tool_calls=tool_calls,
        completed_at=datetime.now(UTC).isoformat(),
    )


def make_bundle(
    *,
    budget_ms: int | None = None,
) -> SimulationBundle:
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
            budgets=SimulationBudgets(performance_budget_ms=budget_ms),
        ),
        review={
            "status": "approved",
            "reviewer": "alice",
            "reviewed_at": "2026-08-08T00:00:00Z",
            "reason": "approved",
        },
    )


def test_identical_runs_mean_no_material_difference() -> None:
    bundle = make_bundle()
    result = compare_runs(make_run(), make_run(), bundle)
    assert result.verdict is ComparisonVerdict.NO_MATERIAL_DIFFERENCE
    assert result.regressions == ()
    assert result.blocked_reasons == ()
    assert result.bundle_id == bundle.bundle_id
    assert result.evidence_ref == bundle.evidence_ref


def test_different_tool_path_alone_is_not_an_improvement() -> None:
    bundle = make_bundle()
    candidate = make_run(tool_calls=("get_order_status", "get_policy"))
    result = compare_runs(make_run(), candidate, bundle)
    assert result.verdict is ComparisonVerdict.NO_MATERIAL_DIFFERENCE
    assert result.regressions == ()
    trajectory = next(d for d in result.deltas if d.criterion == "trajectory")
    assert trajectory.changed is True
    assert trajectory.regression is False


def test_latency_tokens_and_cost_deltas_are_visible_but_not_decisive() -> None:
    bundle = make_bundle()
    baseline = make_run(total_latency_ms=200.0, cost_usd=0.02)
    candidate = make_run(
        total_latency_ms=150.0,
        cost_usd=0.01,
        tool_calls=("get_order_status", "get_policy"),
    )
    result = compare_runs(baseline, candidate, bundle)
    deltas = {delta.criterion: delta for delta in result.deltas}
    assert deltas["latency_ms"].changed is True
    assert deltas["latency_ms"].baseline == "200.00"
    assert deltas["latency_ms"].candidate == "150.00"
    assert deltas["tokens"].changed is False
    assert deltas["cost_usd"].changed is True
    assert result.verdict is ComparisonVerdict.NO_MATERIAL_DIFFERENCE


def test_candidate_passes_when_it_fixes_a_failed_evaluator() -> None:
    bundle = make_bundle()
    baseline = make_run(evaluator_failures=("authorization",))
    result = compare_runs(baseline, make_run(), bundle)
    assert result.verdict is ComparisonVerdict.CANDIDATE_PASSES
    assert result.regressions == ()


def test_candidate_passes_when_it_fixes_the_outcome_match() -> None:
    bundle = make_bundle()
    baseline = make_run(outcome=SupportOutcome.BLOCKED, reason_code=ReasonCode.ORDER_NOT_FOUND)
    result = compare_runs(baseline, make_run(), bundle)
    assert result.verdict is ComparisonVerdict.CANDIDATE_PASSES


def test_candidate_passes_when_it_removes_retries() -> None:
    bundle = make_bundle()
    baseline = make_run(retries=2)
    result = compare_runs(baseline, make_run(retries=0), bundle)
    assert result.verdict is ComparisonVerdict.CANDIDATE_PASSES


def test_safety_regression_blocks_the_candidate() -> None:
    bundle = make_bundle()
    baseline = make_run()
    candidate = make_run(evaluator_failures=("authorization",))
    result = compare_runs(baseline, candidate, bundle)
    assert result.verdict is ComparisonVerdict.CANDIDATE_REGRESSES
    assert "evaluator:authorization" in result.regressions
    assert any("safety regression" in reason for reason in result.blocked_reasons)


def test_outcome_regression_blocks_the_candidate() -> None:
    bundle = make_bundle()
    candidate = make_run(outcome=SupportOutcome.BLOCKED, reason_code=ReasonCode.ORDER_NOT_FOUND)
    result = compare_runs(make_run(), candidate, bundle)
    assert result.verdict is ComparisonVerdict.CANDIDATE_REGRESSES
    assert "outcome" in result.regressions
    assert any("outcome regression" in reason for reason in result.blocked_reasons)


def test_retry_regression_counts_as_regression() -> None:
    bundle = make_bundle()
    candidate = make_run(retries=3)
    result = compare_runs(make_run(), candidate, bundle)
    assert result.verdict is ComparisonVerdict.CANDIDATE_REGRESSES
    assert "retries" in result.regressions


def test_missing_required_measurement_blocks_candidate_passes() -> None:
    bundle = make_bundle(budget_ms=500)
    candidate = make_run(total_latency_ms=None)
    result = compare_runs(make_run(), candidate, bundle)
    assert result.verdict is ComparisonVerdict.INSUFFICIENT_EVIDENCE
    assert any("missing required measurement" in reason for reason in result.blocked_reasons)


def test_uncomparable_run_means_insufficient_evidence() -> None:
    bundle = make_bundle()
    candidate = make_run(verdict=RunVerdict.UNEXPECTED_ACCESS, outcome=SupportOutcome.FAILED)
    result = compare_runs(make_run(), candidate, bundle)
    assert result.verdict is ComparisonVerdict.INSUFFICIENT_EVIDENCE
    assert result.blocked_reasons


def test_budget_regression_counts_as_regression() -> None:
    bundle = make_bundle(budget_ms=500)
    candidate = make_run(
        total_latency_ms=900.0,
        evaluator_failures=("latency",),
    )
    result = compare_runs(make_run(), candidate, bundle)
    assert result.verdict is ComparisonVerdict.CANDIDATE_REGRESSES
    assert "evaluator:latency" in result.regressions
