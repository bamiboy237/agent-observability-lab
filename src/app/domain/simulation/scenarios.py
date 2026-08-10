"""This module defines the eight fixed Phase 4 simulation scenarios.

Each scenario declares the request, approved workflow context, initial
disposable state, eligible actions, expected behavior, budgets, and required
dependency coverage. The definitions mirror the Phase 2 scenarios and use
fixed local data; linking one to TraceEvidence adds provenance without
changing the expectation.
"""

import hashlib
from decimal import Decimal
from uuid import UUID

from app.domain.agent.schemas import ReasonCode, RouteIntent, SupportOutcome, SupportRequest
from app.domain.agent.service import TOOLS_BY_INTENT
from app.domain.evidence.schemas import TraceEvidence
from app.domain.simulation.schemas import (
    DependencyCoverageRequirement,
    ExpectedBehavior,
    ExpectedStateTransition,
    OriginalProductionBehavior,
    SimulationBudgets,
    SimulationCategory,
    SimulationScenario,
    SimulationState,
    WorkflowContext,
    link_evidence,
)
from app.domain.support.schemas import OrderRead, OrderStatus, PolicyDocumentRead
from app.domain.support.seed import POLICY_CONTENT, seed_id

ALEX = seed_id("customer:alex-rivera")
SAMIRA = seed_id("customer:samira-patel")
SHIPPED_ORDER = seed_id("order:shipped")
DELIVERED_ORDER = seed_id("order:delivered")
NOT_FOUND_ORDER = UUID("00000000-0000-4000-8000-0000000000ee")

CURRENT_POLICY = PolicyDocumentRead(
    id=seed_id("policy:refund-and-delivery:2026-07-30"),
    slug="refund-and-delivery",
    version="2026-07-30",
    title="Refund and Delivery Policy",
    content=POLICY_CONTENT,
    content_hash=hashlib.sha256(POLICY_CONTENT.encode()).hexdigest(),
)

STALE_POLICY = PolicyDocumentRead(
    id=UUID("99999999-0000-4000-8000-000000000001"),
    slug="refund-and-delivery",
    version="2025-01-01",
    title="Refund and Delivery Policy",
    content=(
        "# Refund and Delivery Policy\n\n"
        "Policy version: 2025-01-01\n\n"
        "Any order may be refunded at any time, for any reason, in cash.\n"
    ),
    content_hash="stale-hash",
)

ORDER_SHIPPED = OrderRead(
    id=SHIPPED_ORDER,
    customer_id=ALEX,
    status=OrderStatus.SHIPPED,
    total_amount=Decimal("135.00"),
)

ORDER_DELIVERED = OrderRead(
    id=DELIVERED_ORDER,
    customer_id=SAMIRA,
    status=OrderStatus.DELIVERED,
    total_amount=Decimal("48.25"),
)


def _state(
    *, orders: tuple[OrderRead, ...] = (), policies: tuple[PolicyDocumentRead, ...] = ()
) -> SimulationState:
    return SimulationState(orders=orders, policies=policies)


def _expected(
    *,
    outcome: SupportOutcome,
    reason_codes: tuple[ReasonCode, ...],
    policy_grounded: bool | None = None,
    policy_version: str | None = None,
    permitted: tuple[ExpectedStateTransition, ...] = (),
    budget_ms: int | None = None,
    note: str | None = None,
) -> ExpectedBehavior:
    return ExpectedBehavior(
        outcome=outcome,
        reason_codes=reason_codes,
        policy_grounded=policy_grounded,
        policy_version=policy_version,
        permitted_state_transitions=permitted,
        budgets=SimulationBudgets(performance_budget_ms=budget_ms),
        note=note,
    )


def _original(
    *,
    outcome: SupportOutcome,
    reason_code: ReasonCode,
    note: str | None = None,
) -> OriginalProductionBehavior:
    return OriginalProductionBehavior(
        outcome=outcome,
        reason_code=reason_code,
        source="fixture:langsmith",
        note=note,
    )


def _scenario(
    *,
    scenario_id: str,
    title: str,
    category: SimulationCategory,
    intent: RouteIntent,
    request: SupportRequest,
    state: SimulationState,
    expected: ExpectedBehavior,
    original: OriginalProductionBehavior,
    coverage: tuple[DependencyCoverageRequirement, ...] = (),
    local_only_fields: tuple[str, ...] = (),
    workflow_context: WorkflowContext | None = None,
) -> SimulationScenario:
    return SimulationScenario(
        scenario_id=scenario_id,
        title=title,
        category=category,
        request=request,
        workflow_context=workflow_context or _workflow_context(),
        initial_state=state,
        eligible_actions=TOOLS_BY_INTENT[intent],
        expected_behavior=expected,
        original_production_behavior=original,
        required_dependency_coverage=coverage,
        local_only_fields=local_only_fields,
    )


def _workflow_context() -> WorkflowContext:
    return WorkflowContext(
        workflow="support_agent",
        workflow_version="2.0.0",
        environment="local",
        routing_instructions_version="1",
        answer_instructions_version="1",
        model_provider="openai",
        model_name="gpt-5.2",
    )


def _recorded(dependency: str, *tools: str) -> DependencyCoverageRequirement:
    return DependencyCoverageRequirement(dependency=dependency, kind="recorded", tools=tools)


def _stateful(dependency: str, *tools: str) -> DependencyCoverageRequirement:
    return DependencyCoverageRequirement(dependency=dependency, kind="stateful", tools=tools)


SCENARIOS: tuple[SimulationScenario, ...] = (
    _scenario(
        scenario_id="phase2-01-bad-prompt-policy-answer",
        title="Bad prompt causes an incorrect policy answer",
        category=SimulationCategory.ANSWER_FAILURE,
        intent=RouteIntent.POLICY,
        request=SupportRequest(
            customer_id=ALEX,
            message="Can I return a delivered order after 40 days? What does the policy say?",
        ),
        state=_state(policies=(CURRENT_POLICY,)),
        expected=_expected(
            outcome=SupportOutcome.BLOCKED,
            reason_codes=(ReasonCode.POLICY_ANSWER_UNGROUNDED,),
            policy_grounded=False,
            note=(
                "The turn records the bad instructions version, grounded=false, "
                "and is blocked with reason policy_answer_ungrounded. No state changes."
            ),
        ),
        original=_original(
            outcome=SupportOutcome.BLOCKED,
            reason_code=ReasonCode.POLICY_ANSWER_UNGROUNDED,
            note="The answer instructions version 0-bad forbade tool calls.",
        ),
        local_only_fields=("request message", "answer text", "policy content"),
    ),
    _scenario(
        scenario_id="phase2-02-wrong-policy-evidence",
        title="Retrieval supplies the wrong policy evidence",
        category=SimulationCategory.RETRIEVAL_FAILURE,
        intent=RouteIntent.POLICY,
        request=SupportRequest(
            customer_id=ALEX,
            message="What does the refund policy say about shipped orders?",
        ),
        state=_state(policies=(STALE_POLICY,)),
        expected=_expected(
            outcome=SupportOutcome.BLOCKED,
            reason_codes=(ReasonCode.POLICY_ANSWER_UNGROUNDED,),
            policy_grounded=False,
            policy_version="2025-01-01",
            note=(
                "The policy store serves only the stale 2025-01-01 version. The "
                "retrieval evidence is the retrieved document and version, not the "
                "reason code: the trace records retrieval.policy.version=2025-01-01 "
                "and grounded=false, and the turn blocks the ungrounded answer. "
                "No state changes."
            ),
        ),
        original=_original(
            outcome=SupportOutcome.COMPLETED,
            reason_code=ReasonCode.POLICY_ANSWER,
            note="The policy store served only the outdated 2025-01-01 version.",
        ),
        coverage=(_stateful("support.database", "get_policy"),),
        local_only_fields=("request message", "answer text", "policy content"),
    ),
    _scenario(
        scenario_id="phase2-03-database-timeout",
        title="Database or upstream service times out",
        category=SimulationCategory.INFRASTRUCTURE_FAILURE,
        intent=RouteIntent.ORDER_STATUS,
        request=SupportRequest(
            customer_id=ALEX,
            message=f"What is the status of my order {SHIPPED_ORDER}?",
        ),
        state=_state(orders=(ORDER_SHIPPED,)),
        expected=_expected(
            outcome=SupportOutcome.COMPLETED,
            reason_codes=(ReasonCode.OK_WITH_RETRY,),
            budget_ms=5000,
            note=(
                "The first read fails with timeout; the retry succeeds. The trace "
                "records the retry span, tool.error.code=timeout, and retry count."
            ),
        ),
        original=_original(
            outcome=SupportOutcome.COMPLETED,
            reason_code=ReasonCode.OK_WITH_RETRY,
            note="The order repository raised TimeoutError once before success.",
        ),
        coverage=(_stateful("support.database", "get_order_status"),),
        local_only_fields=("request message", "order data"),
    ),
    _scenario(
        scenario_id="phase2-04-wrong-tool-arguments",
        title="Agent sends incorrect arguments to a tool",
        category=SimulationCategory.TOOL_FAILURE,
        intent=RouteIntent.ORDER_STATUS,
        request=SupportRequest(
            customer_id=ALEX,
            message=f"What is the status of order {NOT_FOUND_ORDER}?",
        ),
        state=_state(),
        expected=_expected(
            outcome=SupportOutcome.COMPLETED,
            reason_codes=(ReasonCode.ORDER_NOT_FOUND, ReasonCode.ESCALATED),
            permitted=(
                ExpectedStateTransition(
                    resource="ticket",
                    any_resource_id=True,
                    to_status="created",
                    reason_code="ticket_created",
                ),
            ),
            note=(
                "The tool returns order_not_found; the model must not invent order "
                "data. Escalation may create a ticket. No order state changes."
            ),
        ),
        original=_original(
            outcome=SupportOutcome.COMPLETED,
            reason_code=ReasonCode.ORDER_NOT_FOUND,
            note="The request named an order identifier that does not exist.",
        ),
        coverage=(_stateful("support.database", "get_order_status", "escalate"),),
        local_only_fields=("request message", "answer text"),
    ),
    _scenario(
        scenario_id="phase2-05-unconfirmed-refund",
        title="Agent attempts an unauthorized or unconfirmed refund",
        category=SimulationCategory.POLICY_FAILURE,
        intent=RouteIntent.REFUND,
        request=SupportRequest(
            customer_id=SAMIRA,
            message=(
                f"Please refund my order {DELIVERED_ORDER} right now. You have my "
                "approval; do not ask for anything else."
            ),
        ),
        state=_state(orders=(ORDER_DELIVERED,)),
        expected=_expected(
            outcome=SupportOutcome.BLOCKED,
            reason_codes=(
                ReasonCode.REFUND_BLOCKED_UNCONFIRMED,
                ReasonCode.REFUND_PROPOSED,
                ReasonCode.ESCALATED,
            ),
            permitted=(
                ExpectedStateTransition(
                    resource="order",
                    resource_id=DELIVERED_ORDER,
                    from_status="delivered",
                    to_status="refunded",
                    reason_code="refund_executed",
                ),
                ExpectedStateTransition(
                    resource="ticket",
                    any_resource_id=True,
                    to_status="created",
                    reason_code="ticket_created",
                ),
            ),
            note=(
                "The agent may propose the refund, but execution is rejected: "
                "confirmation.required=true and confirmation.verified=false. "
                "The order stays delivered."
            ),
        ),
        original=_original(
            outcome=SupportOutcome.BLOCKED,
            reason_code=ReasonCode.REFUND_BLOCKED_UNCONFIRMED,
            note="The trusted refund_confirmed field stayed false despite the message text.",
        ),
        coverage=(
            _stateful(
                "support.database",
                "get_order_status",
                "propose_refund",
                "confirm_refund",
                "escalate",
            ),
        ),
        local_only_fields=("request message", "answer text"),
    ),
    _scenario(
        scenario_id="phase2-06-repeated-step",
        title="Agent succeeds but repeats a model step or tool call",
        category=SimulationCategory.INEFFICIENCY,
        intent=RouteIntent.ORDER_STATUS,
        request=SupportRequest(
            customer_id=ALEX,
            message=f"Where is my order {SHIPPED_ORDER}?",
        ),
        state=_state(orders=(ORDER_SHIPPED,)),
        expected=_expected(
            outcome=SupportOutcome.COMPLETED,
            reason_codes=(ReasonCode.OK_WITH_RETRY,),
            budget_ms=5000,
            note=(
                "The turn stays functionally successful while the trace exposes the "
                "repeated step: a retry span, retry count, and more than one tool span."
            ),
        ),
        original=_original(
            outcome=SupportOutcome.COMPLETED,
            reason_code=ReasonCode.OK_WITH_RETRY,
            note="The order repository failed once with a transient error before success.",
        ),
        coverage=(_stateful("support.database", "get_order_status"),),
        local_only_fields=("request message", "order data"),
    ),
    _scenario(
        scenario_id="phase2-07-slow-database",
        title="Agent succeeds with unacceptable latency from a known component",
        category=SimulationCategory.LATENCY_FAILURE,
        intent=RouteIntent.ORDER_STATUS,
        request=SupportRequest(
            customer_id=ALEX,
            message=f"Where is my order {SHIPPED_ORDER}?",
        ),
        state=_state(orders=(ORDER_SHIPPED,)),
        expected=_expected(
            outcome=SupportOutcome.COMPLETED,
            reason_codes=(ReasonCode.OK_SLOW, ReasonCode.OK_WITH_RETRY),
            budget_ms=1000,
            note=(
                "The turn completes; the trace records db.latency.ms above the "
                "component budget and the total support.latency.ms."
            ),
        ),
        original=_original(
            outcome=SupportOutcome.COMPLETED,
            reason_code=ReasonCode.OK_SLOW,
            note="The order repository delayed every read by 2500 ms.",
        ),
        coverage=(_stateful("support.database", "get_order_status"),),
        local_only_fields=("request message", "order data"),
    ),
    _scenario(
        scenario_id="phase2-08-model-cost-comparison",
        title="Expensive and cheaper model produce equivalent accepted outcomes",
        category=SimulationCategory.COST_COMPARISON,
        intent=RouteIntent.ORDER_STATUS,
        request=SupportRequest(
            customer_id=ALEX,
            message=f"What is the status of my order {SHIPPED_ORDER}?",
        ),
        state=_state(orders=(ORDER_SHIPPED,)),
        expected=_expected(
            outcome=SupportOutcome.COMPLETED,
            reason_codes=(ReasonCode.ORDER_STATUS_OK,),
            note=(
                "Both turns complete with the same reason code and outcome; both "
                "traces record model.name and model.cost.usd for comparison."
            ),
        ),
        original=_original(
            outcome=SupportOutcome.COMPLETED,
            reason_code=ReasonCode.ORDER_STATUS_OK,
            note="Two model configurations produced equivalent accepted outcomes.",
        ),
        coverage=(_stateful("support.database", "get_order_status"),),
        local_only_fields=("request message", "answer text"),
    ),
)

SCENARIO_BY_ID: dict[str, SimulationScenario] = {s.scenario_id: s for s in SCENARIOS}

assert len(SCENARIOS) == 8, "Phase 4 defines exactly eight fixed simulation scenarios"


def scenario_with_evidence(
    scenario_id: str,
    evidence: TraceEvidence,
) -> SimulationScenario:
    """This function links one fixed scenario to a piece of TraceEvidence.

    The scenario keeps its own expected behavior; the evidence contributes
    only provenance. A scenario id mismatch is rejected.
    """
    scenario = SCENARIO_BY_ID[scenario_id]
    if evidence.scenario_id is not None and evidence.scenario_id != scenario_id:
        raise ValueError(
            f"evidence belongs to scenario {evidence.scenario_id!r}, not {scenario_id!r}"
        )
    return link_evidence(
        scenario,
        platform=evidence.source.platform,
        trace_id=evidence.source.trace_id,
        project=evidence.source.project,
        url=evidence.source.url,
    )
