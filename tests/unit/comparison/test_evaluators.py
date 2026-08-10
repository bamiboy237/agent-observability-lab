"""This module tests the versioned deterministic evaluators (checkpoint 6.4).

Every criterion that code can express is a versioned evaluator: authorization,
refund confirmation, allowed tools, state transitions, required policy
evidence, output schema, escalation, latency, tokens, and cost. Wrong outputs
and trajectories fail with understandable reasons, and no LLM judge exists.
"""

from uuid import uuid4

from app.domain.agent.schemas import ReasonCode, RouteIntent, SupportOutcome
from app.domain.bundle.schemas import (
    ExpectedBehavior,
    SimulationBundle,
)
from app.domain.comparison.evaluators import (
    ALL_EVALUATORS,
    EvaluatorReport,
    RunMetrics,
    run_evaluators,
)
from app.domain.simulation.adapters import StateMutation
from app.domain.simulation.schemas import (
    ExpectedStateTransition,
    SimulationBudgets,
)


def make_bundle(
    *,
    outcome: SupportOutcome = SupportOutcome.COMPLETED,
    reason_codes: tuple[ReasonCode, ...] = (ReasonCode.ORDER_STATUS_OK,),
    policy_grounded: bool | None = None,
    policy_version: str | None = None,
    transitions: tuple[ExpectedStateTransition, ...] = (),
    permitted: tuple[ExpectedStateTransition, ...] = (),
    budgets: SimulationBudgets | None = None,
    refund_confirmed: bool = False,
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
                "refund_confirmed": refund_confirmed,
            },
            "workflow_context": {
                "workflow": "support_agent",
                "workflow_version": "2.0.0",
            },
            "eligible_actions": [
                "get_order_status",
                "get_policy",
                "propose_refund",
                "confirm_refund",
                "escalate",
            ],
            "required_dependency_coverage": [],
        },
        expected_behavior=ExpectedBehavior(
            outcome=outcome,
            reason_codes=reason_codes,
            policy_grounded=policy_grounded,
            policy_version=policy_version,
            state_transitions=transitions,
            permitted_state_transitions=permitted,
            budgets=budgets or SimulationBudgets(),
        ),
        review={
            "status": "approved",
            "reviewer": "alice",
            "reviewed_at": "2026-08-08T00:00:00Z",
            "reason": "approved",
        },
    )


def make_metrics(
    *,
    outcome: SupportOutcome = SupportOutcome.COMPLETED,
    reason_code: ReasonCode = ReasonCode.ORDER_STATUS_OK,
    intent: RouteIntent = RouteIntent.ORDER_STATUS,
    tool_calls: tuple[str, ...] = ("get_order_status",),
    tool_errors: tuple[str, ...] = (),
    retries: int = 0,
    total_latency_ms: float | None = 100.0,
    tokens: int = 100,
    cost_usd: float | None = 0.01,
    mutations: tuple[StateMutation, ...] = (),
    policy_grounded: bool | None = None,
    retrieved_policy_version: str | None = None,
) -> RunMetrics:
    return RunMetrics(
        outcome=outcome,
        reason_code=reason_code,
        intent=intent,
        tool_calls=tool_calls,
        tool_errors=tool_errors,
        retries=retries,
        total_latency_ms=total_latency_ms,
        tokens=tokens,
        cost_usd=cost_usd,
        mutations=mutations,
        policy_grounded=policy_grounded,
        retrieved_policy_version=retrieved_policy_version,
    )


def results_by_name(report: EvaluatorReport) -> dict[str, bool]:
    return {result.evaluator: result.passed for result in report.results}


def test_every_listed_criterion_has_a_versioned_evaluator() -> None:
    names = {evaluator.name for evaluator in ALL_EVALUATORS}
    assert names == {
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
    }
    assert all(evaluator.version == "1.0.0" for evaluator in ALL_EVALUATORS)


def test_all_evaluators_pass_on_a_clean_run() -> None:
    bundle = make_bundle()
    report = run_evaluators(bundle, make_metrics())
    assert report.all_passed
    assert results_by_name(report) == {name: True for name in results_by_name(report)}


def test_authorization_fails_on_forbidden_access() -> None:
    bundle = make_bundle()
    report = run_evaluators(bundle, make_metrics(tool_errors=("forbidden",)))
    assert results_by_name(report)["authorization"] is False
    failure = next(r for r in report.results if r.evaluator == "authorization")
    assert "forbidden" in failure.reason


def test_refund_confirmation_fails_on_unconfirmed_execution() -> None:
    bundle = make_bundle(refund_confirmed=False)
    mutation = StateMutation(
        sequence=1,
        resource="order",
        resource_id=str(uuid4()),
        field="status",
        before="delivered",
        after="refunded",
        reason_code="refund_executed",
    )
    report = run_evaluators(bundle, make_metrics(mutations=(mutation,)))
    assert results_by_name(report)["refund_confirmation"] is False
    failure = next(r for r in report.results if r.evaluator == "refund_confirmation")
    assert "not confirm" in failure.reason


def test_allowed_tools_fails_on_out_of_scope_tool() -> None:
    bundle = make_bundle()
    report = run_evaluators(
        bundle,
        make_metrics(tool_calls=("get_order_status", "send_email")),
    )
    assert results_by_name(report)["allowed_tools"] is False
    failure = next(r for r in report.results if r.evaluator == "allowed_tools")
    assert "send_email" in failure.reason


def test_state_transitions_fail_when_expected_transition_is_missing() -> None:
    order_id = uuid4()
    transition = ExpectedStateTransition(
        resource="order",
        resource_id=order_id,
        from_status="delivered",
        to_status="refunded",
        reason_code="refund_executed",
    )
    bundle = make_bundle(transitions=(transition,))
    report = run_evaluators(
        bundle,
        make_metrics(
            mutations=(
                StateMutation(
                    sequence=1,
                    resource="ticket",
                    resource_id=str(uuid4()),
                    field="created",
                    before=None,
                    after={},
                    reason_code="ticket_created",
                ),
            )
        ),
    )
    assert results_by_name(report)["state_transitions"] is False
    failure = next(r for r in report.results if r.evaluator == "state_transitions")
    assert "delivered->refunded" in failure.reason


def test_state_transitions_pass_when_mutation_matches() -> None:
    order_id = uuid4()
    transition = ExpectedStateTransition(
        resource="order",
        resource_id=order_id,
        from_status="delivered",
        to_status="refunded",
        reason_code="refund_executed",
    )
    bundle = make_bundle(transitions=(transition,))
    report = run_evaluators(
        bundle,
        make_metrics(
            mutations=(
                StateMutation(
                    sequence=1,
                    resource="order",
                    resource_id=str(order_id),
                    field="status",
                    before="delivered",
                    after="refunded",
                    reason_code="refund_executed",
                ),
            )
        ),
    )
    assert results_by_name(report)["state_transitions"] is True


def test_policy_evidence_fails_when_grounding_mismatches() -> None:
    bundle = make_bundle(
        outcome=SupportOutcome.BLOCKED,
        reason_codes=(ReasonCode.POLICY_ANSWER_UNGROUNDED,),
        policy_grounded=False,
    )
    report = run_evaluators(
        bundle,
        make_metrics(
            outcome=SupportOutcome.BLOCKED,
            reason_code=ReasonCode.POLICY_ANSWER_UNGROUNDED,
            intent=RouteIntent.POLICY,
            policy_grounded=True,
            tool_calls=("get_policy",),
        ),
    )
    assert results_by_name(report)["policy_evidence"] is False
    failure = next(r for r in report.results if r.evaluator == "policy_evidence")
    assert "grounded" in failure.reason


def test_policy_evidence_fails_on_wrong_retrieved_version() -> None:
    bundle = make_bundle(
        outcome=SupportOutcome.BLOCKED,
        reason_codes=(ReasonCode.POLICY_ANSWER_UNGROUNDED,),
        policy_grounded=False,
        policy_version="2025-01-01",
    )
    report = run_evaluators(
        bundle,
        make_metrics(
            outcome=SupportOutcome.BLOCKED,
            reason_code=ReasonCode.POLICY_ANSWER_UNGROUNDED,
            intent=RouteIntent.POLICY,
            policy_grounded=False,
            tool_calls=("get_policy",),
            retrieved_policy_version="2026-07-30",
        ),
    )
    assert results_by_name(report)["policy_evidence"] is False
    failure = next(r for r in report.results if r.evaluator == "policy_evidence")
    assert "2025-01-01" in failure.reason
    assert "2026-07-30" in failure.reason


def test_policy_evidence_fails_when_expected_version_is_never_retrieved() -> None:
    bundle = make_bundle(
        outcome=SupportOutcome.BLOCKED,
        reason_codes=(ReasonCode.POLICY_ANSWER_UNGROUNDED,),
        policy_grounded=False,
        policy_version="2025-01-01",
    )
    report = run_evaluators(
        bundle,
        make_metrics(
            outcome=SupportOutcome.BLOCKED,
            reason_code=ReasonCode.POLICY_ANSWER_UNGROUNDED,
            intent=RouteIntent.POLICY,
            policy_grounded=False,
            tool_calls=(),
        ),
    )
    assert results_by_name(report)["policy_evidence"] is False
    failure = next(r for r in report.results if r.evaluator == "policy_evidence")
    assert "never retrieved" in failure.reason


def test_policy_evidence_passes_when_stale_version_is_retrieved_and_ungrounded() -> None:
    bundle = make_bundle(
        outcome=SupportOutcome.BLOCKED,
        reason_codes=(ReasonCode.POLICY_ANSWER_UNGROUNDED,),
        policy_grounded=False,
        policy_version="2025-01-01",
    )
    report = run_evaluators(
        bundle,
        make_metrics(
            outcome=SupportOutcome.BLOCKED,
            reason_code=ReasonCode.POLICY_ANSWER_UNGROUNDED,
            intent=RouteIntent.POLICY,
            policy_grounded=False,
            tool_calls=("get_policy",),
            retrieved_policy_version="2025-01-01",
        ),
    )
    assert results_by_name(report)["policy_evidence"] is True


def test_policy_evidence_fails_when_grounded_answer_has_no_retrieval() -> None:
    bundle = make_bundle()
    report = run_evaluators(
        bundle,
        make_metrics(
            reason_code=ReasonCode.POLICY_ANSWER,
            intent=RouteIntent.POLICY,
            policy_grounded=True,
            tool_calls=(),
        ),
    )
    assert results_by_name(report)["policy_evidence"] is False
    failure = next(r for r in report.results if r.evaluator == "policy_evidence")
    assert "never retrieved" in failure.reason


def test_unexpected_state_changes_fail_when_none_permitted() -> None:
    bundle = make_bundle()
    mutation = StateMutation(
        sequence=1,
        resource="order",
        resource_id=str(uuid4()),
        field="status",
        before="delivered",
        after="refunded",
        reason_code="refund_executed",
    )
    report = run_evaluators(bundle, make_metrics(mutations=(mutation,)))
    assert results_by_name(report)["unexpected_state_changes"] is False
    failure = next(r for r in report.results if r.evaluator == "unexpected_state_changes")
    assert "refund_executed" in failure.measured["unexpected_mutations"]


def test_unexpected_state_changes_pass_when_mutation_is_permitted() -> None:
    order_id = uuid4()
    permitted = ExpectedStateTransition(
        resource="order",
        resource_id=order_id,
        from_status="delivered",
        to_status="refunded",
        reason_code="refund_executed",
    )
    bundle = make_bundle(permitted=(permitted,))
    mutation = StateMutation(
        sequence=1,
        resource="order",
        resource_id=str(order_id),
        field="status",
        before="delivered",
        after="refunded",
        reason_code="refund_executed",
    )
    report = run_evaluators(bundle, make_metrics(mutations=(mutation,)))
    assert results_by_name(report)["unexpected_state_changes"] is True


def test_unexpected_state_changes_fail_on_other_state_with_permits() -> None:
    bundle = make_bundle(
        permitted=(
            ExpectedStateTransition(
                resource="ticket",
                resource_id=uuid4(),
                to_status="created",
                reason_code="ticket_created",
            ),
        )
    )
    mutation = StateMutation(
        sequence=1,
        resource="order",
        resource_id=str(uuid4()),
        field="status",
        before="delivered",
        after="refunded",
        reason_code="refund_executed",
    )
    report = run_evaluators(bundle, make_metrics(mutations=(mutation,)))
    assert results_by_name(report)["unexpected_state_changes"] is False
    failure = next(r for r in report.results if r.evaluator == "unexpected_state_changes")
    assert "order" in failure.measured["unexpected_mutations"]


def test_escalation_requires_a_ticket_when_expected() -> None:
    bundle = make_bundle(
        outcome=SupportOutcome.ESCALATED,
        reason_codes=(ReasonCode.ESCALATED,),
    )
    report = run_evaluators(
        bundle,
        make_metrics(
            outcome=SupportOutcome.ESCALATED,
            reason_code=ReasonCode.ESCALATED,
            intent=RouteIntent.ESCALATE,
            tool_calls=(),
        ),
    )
    assert results_by_name(report)["escalation"] is False
    failure = next(r for r in report.results if r.evaluator == "escalation")
    assert "never called" in failure.reason


def test_escalation_passes_when_escalation_is_optional() -> None:
    bundle = make_bundle(
        reason_codes=(ReasonCode.ORDER_NOT_FOUND, ReasonCode.ESCALATED),
    )
    report = run_evaluators(
        bundle,
        make_metrics(
            reason_code=ReasonCode.ORDER_NOT_FOUND,
            tool_calls=("get_order_status",),
        ),
    )
    assert results_by_name(report)["escalation"] is True


def test_escalation_fails_when_escalated_without_a_ticket() -> None:
    bundle = make_bundle(
        reason_codes=(ReasonCode.ORDER_NOT_FOUND, ReasonCode.ESCALATED),
    )
    report = run_evaluators(
        bundle,
        make_metrics(
            reason_code=ReasonCode.ORDER_NOT_FOUND,
            tool_calls=("get_order_status", "escalate"),
        ),
    )
    assert results_by_name(report)["escalation"] is False
    failure = next(r for r in report.results if r.evaluator == "escalation")
    assert "no support ticket" in failure.reason


def test_latency_budget_fails_when_exceeded() -> None:
    bundle = make_bundle(budgets=SimulationBudgets(performance_budget_ms=100))
    report = run_evaluators(bundle, make_metrics(total_latency_ms=250.0))
    assert results_by_name(report)["latency"] is False
    failure = next(r for r in report.results if r.evaluator == "latency")
    assert "250.0" in failure.reason


def test_tokens_budget_fails_when_exceeded() -> None:
    bundle = make_bundle(budgets=SimulationBudgets(max_tokens=500))
    report = run_evaluators(bundle, make_metrics(tokens=900))
    assert results_by_name(report)["tokens"] is False


def test_cost_budget_fails_when_exceeded() -> None:
    bundle = make_bundle(budgets=SimulationBudgets(max_cost_usd=0.01))
    report = run_evaluators(bundle, make_metrics(cost_usd=0.05))
    assert results_by_name(report)["cost"] is False


def test_budget_evaluators_pass_without_declared_budgets() -> None:
    bundle = make_bundle()
    report = run_evaluators(
        bundle, make_metrics(total_latency_ms=9999.0, tokens=99999, cost_usd=9.9)
    )
    assert results_by_name(report)["latency"] is True
    assert results_by_name(report)["tokens"] is True
    assert results_by_name(report)["cost"] is True
