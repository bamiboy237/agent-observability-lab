"""Small, injectable LangGraph node factories for support workflows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from langgraph.types import RetryPolicy, interrupt

from app.domain.agent.schemas import (
    AnswerContext,
    ReasonCode,
    RouteIntent,
    RoutingDecision,
    SupportOutcome,
    SupportResponse,
)
from app.domain.support.errors import Forbidden, InvalidTransition, OrderNotFound, PolicyNotFound
from app.domain.support.schemas import OrderRead, PolicyDocumentRead, TicketRead
from app.domain.workflow.errors import (
    TransientModelError,
    TransientRetrievalError,
    UnsafeWorkflowError,
)
from app.domain.workflow.models import (
    Confirmation,
    ConfirmationDecision,
    EscalationState,
    EvidenceBundle,
    ProposedAction,
    SupportState,
    Transition,
    WorkflowErrorDetail,
)
from app.telemetry.recorder import TraceRecorder

MAX_NODE_ATTEMPTS = 2
RETRY_POLICY = RetryPolicy(
    max_attempts=MAX_NODE_ATTEMPTS,
    retry_on=(TransientModelError, TransientRetrievalError),
)


class Router(Protocol):
    async def route(self, message: str) -> RoutingDecision: ...


class OrderRetriever(Protocol):
    async def get_order(self, order_id: UUID, actor_id: UUID) -> OrderRead: ...


class PolicyRetriever(Protocol):
    async def get_policy(self, slug: str) -> PolicyDocumentRead: ...


class ResponseGenerator(Protocol):
    async def generate(
        self,
        message: str,
        route: RoutingDecision,
        evidence: EvidenceBundle,
        proposal: ProposedAction | None,
    ) -> str: ...


class RefundProposer(Protocol):
    async def propose(
        self,
        actor_id: UUID,
        request_id: str,
        order: OrderRead,
        policy: PolicyDocumentRead | None,
    ) -> ProposedAction: ...


class RefundExecutor(Protocol):
    async def execute(self, actor_id: UUID, order_id: UUID) -> OrderRead: ...


class Escalator(Protocol):
    async def escalate(self, actor_id: UUID, reason_code: str, request_id: str) -> TicketRead: ...


@dataclass
class AttemptTracker:
    """This tracker lets a node emit a typed escalation after bounded retries."""

    attempts: dict[tuple[str, str], int] = field(default_factory=dict)

    def next(self, state: SupportState, node: str) -> int:
        key = (state.get("run_id", ""), node)
        attempt = self.attempts.get(key, 0) + 1
        self.attempts[key] = attempt
        return attempt


@dataclass(frozen=True)
class WorkflowNodeDependencies:
    router: Router
    order_retriever: OrderRetriever
    policy_retriever: PolicyRetriever
    response_generator: ResponseGenerator
    refund_proposer: RefundProposer
    refund_executor: RefundExecutor
    escalator: Escalator
    recorder: TraceRecorder
    attempts: AttemptTracker = field(default_factory=AttemptTracker)


def _transition(state: SupportState, node: str, status: str, *keys: str) -> tuple[Transition, ...]:
    return (*state.get("transcript", ()), Transition(node=node, status=status, changed_keys=keys))


def _error_delta(state: SupportState, error: Exception, *, retryable: bool) -> dict[str, object]:
    details = (*state.get("errors", ()), WorkflowErrorDetail(
        code=type(error).__name__,
        message=str(error)[:400] or "Workflow dependency failed",
        retryable=retryable,
    ))
    return {"errors": details}


def _escalation_delta(
    state: SupportState,
    reason_code: str,
    *,
    error: Exception | None = None,
) -> dict[str, object]:
    delta: dict[str, object] = {
        "escalation": EscalationState(reason_code=reason_code),
        "status": "escalating",
        "transcript": _transition(state, "escalate", "pending", "escalation"),
    }
    if error is not None:
        delta.update(_error_delta(state, error, retryable=False))
    return delta


def make_route_node(
    deps: WorkflowNodeDependencies,
) -> Callable[[SupportState], Awaitable[dict[str, object]]]:
    async def route_node(state: SupportState) -> dict[str, object]:
        request = state["request"]
        with deps.recorder.span("support.workflow.node.route") as span:
            attempt = deps.attempts.next(state, "route")
            try:
                route = await deps.router.route(request.message)
                span.set_attribute("workflow.route", route.intent.value)
            except TransientModelError as error:
                if attempt < MAX_NODE_ATTEMPTS:
                    raise
                delta = _escalation_delta(state, "model_retry_exhausted", error=error)
                delta["transcript"] = _transition(
                    state, "route", "escalated", "escalation", "errors"
                )
                return delta
            except UnsafeWorkflowError as error:
                delta = _escalation_delta(state, "unsafe_routing", error=error)
                delta["transcript"] = _transition(
                    state, "route", "escalated", "escalation", "errors"
                )
                return delta
            return {
                "route": route,
                "status": "routed",
                "transcript": _transition(state, "route", "completed", "route"),
            }

    return route_node


def make_order_node(
    deps: WorkflowNodeDependencies,
) -> Callable[[SupportState], Awaitable[dict[str, object]]]:
    async def retrieve_order_node(state: SupportState) -> dict[str, object]:
        request = state["request"]
        route = state["route"]
        if route.order_id is None:
            return _escalation_delta(state, "missing_order_reference")
        with deps.recorder.span("support.workflow.node.retrieve_order"):
            attempt = deps.attempts.next(state, "retrieve_order")
            try:
                order = await deps.order_retriever.get_order(route.order_id, request.actor_id)
            except TransientRetrievalError as error:
                if attempt < MAX_NODE_ATTEMPTS:
                    raise
                delta = _escalation_delta(state, "retrieval_retry_exhausted", error=error)
                delta["transcript"] = _transition(
                    state, "retrieve_order", "escalated", "escalation", "errors"
                )
                return delta
            except (Forbidden, OrderNotFound, InvalidTransition, UnsafeWorkflowError) as error:
                delta = _escalation_delta(state, "order_access_denied", error=error)
                delta["transcript"] = _transition(
                    state, "retrieve_order", "escalated", "escalation", "errors"
                )
                return delta
            return {
                "evidence": (state.get("evidence") or EvidenceBundle()).model_copy(
                    update={"order": order}
                ),
                "status": "evidence_ready",
                "transcript": _transition(state, "retrieve_order", "completed", "evidence"),
            }

    return retrieve_order_node


def make_policy_node(
    deps: WorkflowNodeDependencies,
) -> Callable[[SupportState], Awaitable[dict[str, object]]]:
    async def retrieve_policy_node(state: SupportState) -> dict[str, object]:
        route = state["route"]
        slug = route.policy_slug
        if slug is None:
            return _escalation_delta(state, "missing_policy_reference")
        with deps.recorder.span("support.workflow.node.retrieve_policy"):
            attempt = deps.attempts.next(state, "retrieve_policy")
            try:
                policy = await deps.policy_retriever.get_policy(slug)
            except TransientRetrievalError as error:
                if attempt < MAX_NODE_ATTEMPTS:
                    raise
                delta = _escalation_delta(state, "retrieval_retry_exhausted", error=error)
                delta["transcript"] = _transition(
                    state, "retrieve_policy", "escalated", "escalation", "errors"
                )
                return delta
            except (PolicyNotFound, UnsafeWorkflowError) as error:
                delta = _escalation_delta(state, "policy_evidence_unavailable", error=error)
                delta["transcript"] = _transition(
                    state, "retrieve_policy", "escalated", "escalation", "errors"
                )
                return delta
            return {
                "evidence": (state.get("evidence") or EvidenceBundle()).model_copy(
                    update={"policy": policy}
                ),
                "status": "evidence_ready",
                "transcript": _transition(state, "retrieve_policy", "completed", "evidence"),
            }

    return retrieve_policy_node


def make_proposal_node(
    deps: WorkflowNodeDependencies,
) -> Callable[[SupportState], Awaitable[dict[str, object]]]:
    async def propose_refund_node(state: SupportState) -> dict[str, object]:
        request = state["request"]
        evidence = state.get("evidence") or EvidenceBundle()
        if evidence.order is None:
            return _escalation_delta(state, "missing_order_evidence")
        with deps.recorder.span("support.workflow.node.propose_refund"):
            try:
                proposal = await deps.refund_proposer.propose(
                    request.actor_id,
                    request.request_id,
                    evidence.order,
                    evidence.policy,
                )
            except (Forbidden, InvalidTransition, OrderNotFound, UnsafeWorkflowError) as error:
                delta = _escalation_delta(state, "refund_action_unsafe", error=error)
                delta["transcript"] = _transition(
                    state, "propose_refund", "escalated", "escalation", "errors"
                )
                return delta
            return {
                "proposed_action": proposal,
                "confirmation": Confirmation(
                    actor_id=request.actor_id,
                    request_id=request.request_id,
                ),
                "status": "awaiting_confirmation",
                "transcript": _transition(
                    state, "propose_refund", "interrupted", "proposed_action", "confirmation"
                ),
            }

    return propose_refund_node


def make_confirmation_node(
    deps: WorkflowNodeDependencies,
) -> Callable[[SupportState], Awaitable[dict[str, object]]]:
    async def confirmation_node(state: SupportState) -> dict[str, object]:
        proposal = state.get("proposed_action")
        request = state["request"]
        if proposal is None:
            return _escalation_delta(state, "missing_refund_proposal")
        decision = interrupt(
            {
                "type": "refund_confirmation",
                "workflow_id": state["workflow_id"],
                "run_id": state["run_id"],
                "actor_id": str(request.actor_id),
                "request_id": request.request_id,
                "proposal": proposal.model_dump(mode="json"),
            }
        )
        if not isinstance(decision, dict):
            raise UnsafeWorkflowError("Confirmation must be a decision object")
        actor_id = decision.get("actor_id")
        request_id = decision.get("request_id")
        if actor_id != str(request.actor_id) or request_id != request.request_id:
            raise UnsafeWorkflowError("Confirmation identity does not match the workflow")
        try:
            selected = ConfirmationDecision(str(decision.get("decision")))
        except ValueError as error:
            raise UnsafeWorkflowError("Confirmation must be confirm or reject") from error
        if selected is ConfirmationDecision.PENDING:
            raise UnsafeWorkflowError("Confirmation must be confirm or reject")
        confirmation = Confirmation(
            decision=selected,
            actor_id=request.actor_id,
            request_id=request.request_id,
            decided_at=datetime.now(UTC),
        )
        status = "confirmed" if selected is ConfirmationDecision.CONFIRM else "rejected"
        return {
            "confirmation": confirmation,
            "status": status,
            "transcript": _transition(state, "confirmation", status, "confirmation"),
        }

    return confirmation_node


def make_execute_node(
    deps: WorkflowNodeDependencies,
) -> Callable[[SupportState], Awaitable[dict[str, object]]]:
    async def execute_refund_node(state: SupportState) -> dict[str, object]:
        proposal = state.get("proposed_action")
        confirmation = state.get("confirmation")
        if proposal is None or confirmation is None:
            return _escalation_delta(state, "missing_confirmation", error=UnsafeWorkflowError())
        if confirmation.decision is not ConfirmationDecision.CONFIRM:
            return {
                "status": "rejected",
                "transcript": _transition(state, "execute_refund", "skipped", "status"),
            }
        with deps.recorder.span("support.workflow.node.execute_refund"):
            try:
                order = await deps.refund_executor.execute(
                    confirmation.actor_id,
                    proposal.order_id,
                )
            except (Forbidden, InvalidTransition, OrderNotFound, UnsafeWorkflowError) as error:
                delta = _escalation_delta(state, "refund_execution_unsafe", error=error)
                delta["transcript"] = _transition(
                    state, "execute_refund", "escalated", "escalation", "errors"
                )
                return delta
            response = SupportResponse(
                intent=RouteIntent.REFUND,
                outcome=SupportOutcome.COMPLETED,
                reason_code=ReasonCode.REFUND_CONFIRMED,
                message="Your refund was confirmed and the order is now marked as refunded.",
                context=AnswerContext(routing=state["route"], order=order),
            )
            return {
                "evidence": (state.get("evidence") or EvidenceBundle()).model_copy(
                    update={"order": order}
                ),
                "response": response,
                "status": "completed",
                "transcript": _transition(
                    state, "execute_refund", "completed", "evidence", "response", "status"
                ),
            }

    return execute_refund_node


def make_rejection_node(
    deps: WorkflowNodeDependencies,
) -> Callable[[SupportState], Awaitable[dict[str, object]]]:
    async def rejection_node(state: SupportState) -> dict[str, object]:
        route = state["route"]
        response = SupportResponse(
            intent=route.intent,
            outcome=SupportOutcome.BLOCKED,
            reason_code=ReasonCode.REFUND_BLOCKED_UNCONFIRMED,
            message="No refund was made because the proposed action was rejected.",
            context=AnswerContext(
                routing=route,
                order=(state.get("evidence") or EvidenceBundle()).order,
            ),
        )
        return {
            "response": response,
            "status": "rejected",
            "transcript": _transition(state, "reject", "completed", "response", "status"),
        }

    return rejection_node


def make_response_node(
    deps: WorkflowNodeDependencies,
) -> Callable[[SupportState], Awaitable[dict[str, object]]]:
    async def response_node(state: SupportState) -> dict[str, object]:
        request = state["request"]
        route = state["route"]
        evidence = state.get("evidence") or EvidenceBundle()
        with deps.recorder.span("support.workflow.node.respond"):
            attempt = deps.attempts.next(state, "respond")
            try:
                message = await deps.response_generator.generate(
                    request.message,
                    route,
                    evidence,
                    state.get("proposed_action"),
                )
            except TransientModelError as error:
                if attempt < MAX_NODE_ATTEMPTS:
                    raise
                delta = _escalation_delta(state, "model_retry_exhausted", error=error)
                delta["transcript"] = _transition(
                    state, "respond", "escalated", "escalation", "errors"
                )
                return delta
            except UnsafeWorkflowError as error:
                delta = _escalation_delta(state, "unsafe_response", error=error)
                delta["transcript"] = _transition(
                    state, "respond", "escalated", "escalation", "errors"
                )
                return delta
            response = SupportResponse(
                intent=route.intent,
                outcome=SupportOutcome.COMPLETED,
                reason_code=(
                    ReasonCode.ORDER_STATUS_OK
                    if route.intent is RouteIntent.ORDER_STATUS
                    else ReasonCode.POLICY_ANSWER
                ),
                message=message,
                context=AnswerContext(routing=route, order=evidence.order, policy=evidence.policy),
            )
            return {
                "response": response,
                "status": "completed",
                "transcript": _transition(state, "respond", "completed", "response", "status"),
            }

    return response_node


def make_escalation_node(
    deps: WorkflowNodeDependencies,
) -> Callable[[SupportState], Awaitable[dict[str, object]]]:
    async def escalation_node(state: SupportState) -> dict[str, object]:
        request = state["request"]
        escalation = state.get("escalation")
        reason = escalation.reason_code if escalation is not None else "requested_by_route"
        ticket = await deps.escalator.escalate(request.actor_id, reason, request.request_id)
        response = SupportResponse(
            intent=RouteIntent.ESCALATE,
            outcome=SupportOutcome.ESCALATED,
            reason_code=ReasonCode.ESCALATED,
            message="I have handed this request to a human support agent.",
            context=AnswerContext(
                routing=state.get("route")
                or RoutingDecision(intent=RouteIntent.ESCALATE, confidence=1.0),
            ),
        )
        return {
            "escalation": EscalationState(
                reason_code=reason,
                status="completed",
                ticket_id=ticket.id,
            ),
            "response": response,
            "status": "escalated",
            "transcript": _transition(
                state, "escalate", "completed", "escalation", "response", "status"
            ),
        }

    return escalation_node
