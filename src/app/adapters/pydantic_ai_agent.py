"""This module provides the adapter for the reference support agent.

The adapter supports hosted model providers.

This module contains the only Pydantic AI SDK types in the application.
Other modules use ``SupportRequest``, ``RoutingDecision``, and ``SupportResponse``.
Settings create the ``ModelConfig`` value for the hosted model.
The tools enforce the deterministic rules from :mod:`app.domain.agent.service`.
The ``TraceRecorder`` emits each span after it removes sensitive values.
"""

import uuid
from dataclasses import dataclass
from time import perf_counter
from typing import Literal, NoReturn

from pydantic import BaseModel, Field, SecretStr
from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimits
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from app.domain.agent.errors import RefundNotConfirmed
from app.domain.agent.instructions import (
    ACCEPTED_ANSWER_INSTRUCTIONS_VERSION,
    ACCEPTED_POLICY_VERSION,
    ANSWER_INSTRUCTIONS,
    ANSWER_INSTRUCTIONS_VERSION,
    POLICY_SLUG,
    ROUTING_INSTRUCTIONS,
    ROUTING_INSTRUCTIONS_VERSION,
    WORKFLOW_VERSION,
)
from app.domain.agent.schemas import (
    AnswerContext,
    ReasonCode,
    RouteIntent,
    RoutingDecision,
    SupportOutcome,
    SupportRequest,
    SupportResponse,
)
from app.domain.agent.service import (
    TOOLS_BY_INTENT,
    SupportAgentService,
    escalate_turn,
    plan_turn,
)
from app.domain.retrieval.answers import build_cited_policy_answer
from app.domain.retrieval.contracts import Retriever
from app.domain.retrieval.errors import HallucinatedCitation, RetrievalError
from app.domain.support.errors import Forbidden, InvalidTransition, OrderNotFound, PolicyNotFound
from app.domain.support.repository import SupportRepository
from app.domain.support.service import SupportService
from app.telemetry.recorder import TraceRecorder, TraceSpan

_PROVIDER = Literal["openai", "anthropic"]

_ROUTING_USAGE_LIMIT = UsageLimits(request_limit=2)
_ANSWER_USAGE_LIMIT = UsageLimits(request_limit=8)
_TOOL_RETRIES = 1


class ModelConfig(BaseModel):
    """This class stores settings for a hosted model that supports both providers."""

    provider: _PROVIDER
    name: str = Field(min_length=1)
    base_url: str | None = None
    api_key: SecretStr | None = None


def build_pydantic_ai_model(config: ModelConfig) -> Model:
    """This function builds a Pydantic AI model from one provider configuration."""
    api_key = config.api_key.get_secret_value() if config.api_key is not None else None
    if config.provider == "openai":
        if config.base_url is not None:
            # Custom OpenAI-compatible endpoints speak chat completions only.
            return OpenAIChatModel(
                config.name,
                provider=OpenAIProvider(base_url=config.base_url, api_key=api_key),
            )
        # The OpenAI API itself: use the modern Responses API. GPT-5.x models
        # reject function tools with reasoning on the legacy chat completions path.
        return OpenAIResponsesModel(
            config.name,
            provider=OpenAIProvider(api_key=api_key),
        )
    if config.base_url is not None or api_key is not None:
        return AnthropicModel(
            config.name,
            provider=AnthropicProvider(base_url=config.base_url, api_key=api_key),
        )
    return AnthropicModel(config.name)


class AnswerDraft(BaseModel):
    """This class stores the model's final answer without model identifiers."""

    intent: RouteIntent
    message: str = Field(min_length=1, max_length=4000)
    citations: tuple[str, ...] = ()


@dataclass
class AgentDeps:
    """This class stores dependencies for one turn.

    The application binds the customer identity here.
    The model cannot choose the customer identity.
    """

    customer_id: uuid.UUID
    service: SupportAgentService
    recorder: TraceRecorder
    retry_count: int = 0


class _UsageTracker:
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cost: float | None = None

    def add(self, usage: object) -> None:
        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)
        total_tokens = getattr(usage, "total_tokens", 0)
        cost = getattr(usage, "cost", None)
        self.input_tokens += int(input_tokens or 0)
        self.output_tokens += int(output_tokens or 0)
        self.total_tokens += int(total_tokens or 0)
        if cost is not None:
            self.cost = (self.cost or 0.0) + float(cost)


def _transient_failure(deps: AgentDeps, span: TraceSpan, error: Exception) -> NoReturn:
    """This function records a retry span and asks the model to repeat the tool call."""
    deps.retry_count += 1
    with deps.recorder.span("support_agent.retry") as retry_span:
        retry_span.set_attribute("support.retry.count", deps.retry_count)
        retry_span.set_attribute("tool.error.code", ReasonCode.TIMEOUT.value)
        retry_span.set_error(ReasonCode.TIMEOUT.value)
    span.set_attribute("tool.error.code", ReasonCode.TIMEOUT.value)
    raise ModelRetry("The service timed out. Try the same call once more.") from error


def _tool_outcome(span: TraceSpan, reason: ReasonCode) -> None:
    span.set_attribute("support.reason.code", reason.value)


class PydanticAISupportAgent:
    """This class provides a typed support agent through Pydantic AI."""

    def __init__(
        self,
        *,
        model_config: ModelConfig,
        recorder: TraceRecorder,
        repository: SupportRepository,
        answer_instructions: str = ANSWER_INSTRUCTIONS,
        answer_instructions_version: str = ANSWER_INSTRUCTIONS_VERSION,
        tools_override: tuple[str, ...] | None = None,
        policy_retriever: Retriever | None = None,
    ) -> None:
        self._model_config = model_config
        self._recorder = recorder
        self._repository = repository
        self._answer_instructions = answer_instructions
        self._answer_instructions_version = answer_instructions_version
        self._tools_override = tools_override
        self._policy_retriever = policy_retriever
        self._last_grounded: bool | None = None
        self._model = build_pydantic_ai_model(model_config)
        self._routing_agent = self._build_routing_agent()
        self._answer_agents = self._build_answer_agents()

    # ------------------------------------------------------------------
    # Agent construction
    # ------------------------------------------------------------------
    def _build_routing_agent(self) -> Agent[AgentDeps, RoutingDecision]:
        return Agent(
            self._model,
            deps_type=AgentDeps,
            output_type=RoutingDecision,
            instructions=ROUTING_INSTRUCTIONS,
            retries=1,
            defer_model_check=True,
            name="support-routing",
        )

    def _build_answer_agents(self) -> dict[RouteIntent, Agent[AgentDeps, AnswerDraft]]:
        agents: dict[RouteIntent, Agent[AgentDeps, AnswerDraft]] = {}
        for intent, tools in TOOLS_BY_INTENT.items():
            agent = Agent(
                self._model,
                deps_type=AgentDeps,
                output_type=AnswerDraft,
                instructions=self._answer_instructions,
                retries=2,
                defer_model_check=True,
                name=f"support-answer-{intent.value}",
            )
            allowed = self._tools_override if self._tools_override is not None else tools
            self._register_tools(agent, allowed)
            agents[intent] = agent
        return agents

    def _register_tools(self, agent: Agent[AgentDeps, AnswerDraft], names: tuple[str, ...]) -> None:
        if "get_order_status" in names:
            agent.tool(retries=_TOOL_RETRIES)(_get_order_status)
        if "get_policy" in names:
            agent.tool(retries=_TOOL_RETRIES)(_get_policy)
        if "propose_refund" in names:
            agent.tool(retries=0)(_propose_refund)
        if "confirm_refund" in names:
            agent.tool(retries=0)(_confirm_refund)
        if "escalate" in names:
            agent.tool(retries=0)(_escalate)

    # ------------------------------------------------------------------
    # Turn orchestration
    # ------------------------------------------------------------------
    async def handle(self, request: SupportRequest) -> SupportResponse:
        """This method runs one complete support turn and returns its typed response."""
        recorder = self._recorder
        self._last_grounded = None
        started_at = perf_counter()
        service = SupportAgentService(
            SupportService(self._repository),
            customer_id=request.customer_id,
            recorder=recorder,
            refund_confirmed=request.refund_confirmed,
            policy_retriever=self._policy_retriever,
        )
        service.set_request_message(request.message)
        deps = AgentDeps(
            customer_id=request.customer_id,
            service=service,
            recorder=recorder,
        )
        usage = _UsageTracker()

        with recorder.span(
            "support_agent.turn",
            {
                "agent.workflow.version": WORKFLOW_VERSION,
                "prompt.version": ROUTING_INSTRUCTIONS_VERSION,
                "agent.routing.instructions.version": ROUTING_INSTRUCTIONS_VERSION,
                "agent.answer.instructions.version": self._answer_instructions_version,
                "agent.model.provider": self._model_config.provider,
                "agent.model.name": self._model_config.name,
                "support.message.length": len(request.message),
            },
        ) as turn_span:
            routing = await self._route(request, deps, usage, turn_span)
            if routing is None:
                response = self._failed_response()
            else:
                turn_span.set_attribute("support.intent", routing.intent.value)
                turn_span.set_attribute("support.confidence", routing.confidence)
                plan = plan_turn(routing)
                if plan.action == "escalate":
                    response = await escalate_turn(service, routing, plan.reason_code)
                else:
                    response = await self._answer(request, routing, deps, usage, turn_span)
            turn_span.set_attribute("support.outcome", response.outcome.value)
            turn_span.set_attribute("support.reason.code", response.reason_code.value)
            if self._last_grounded is not None:
                turn_span.set_attribute("support.policy.grounded", self._last_grounded)
            turn_span.set_attribute(
                "support.latency.ms",
                round((perf_counter() - started_at) * 1000, 2),
            )
            turn_span.set_attribute("support.tokens.input", usage.input_tokens)
            turn_span.set_attribute("support.tokens.output", usage.output_tokens)
            turn_span.set_attribute("support.tokens.total", usage.total_tokens)
            if usage.cost is not None:
                turn_span.set_attribute("support.cost.usd", round(usage.cost, 6))
            turn_span.set_attribute("support.retry.count", deps.retry_count)
            response.trace_id = recorder.current_trace_id()
            return response

    async def _route(
        self,
        request: SupportRequest,
        deps: AgentDeps,
        usage: _UsageTracker,
        turn_span: TraceSpan,
    ) -> RoutingDecision | None:
        try:
            with self._recorder.span("support_agent.routing") as span:
                model_started_at = perf_counter()
                result = await self._routing_agent.run(
                    request.message,
                    deps=deps,
                    usage_limits=_ROUTING_USAGE_LIMIT,
                )
                output = result.output
                if output is None:
                    raise UnexpectedModelBehavior("Routing agent returned no decision")
                usage.add(result.usage)
                span.set_attribute(
                    "model.latency.ms",
                    round((perf_counter() - model_started_at) * 1000, 2),
                )
                span.set_attribute("model.tokens.input", result.usage.input_tokens)
                span.set_attribute("model.tokens.output", result.usage.output_tokens)
                span.set_attribute("model.tokens.total", result.usage.total_tokens)
                if result.usage.cost is not None:
                    span.set_attribute("model.cost.usd", float(result.usage.cost))
                span.set_attribute("model.run.id", result.run_id)
                span.set_attribute("support.intent", output.intent.value)
                span.set_attribute("support.confidence", output.confidence)
                return output
        except Exception:
            turn_span.set_attribute("support.reason.code", ReasonCode.MODEL_ERROR.value)
            return None

    async def _answer(
        self,
        request: SupportRequest,
        routing: RoutingDecision,
        deps: AgentDeps,
        usage: _UsageTracker,
        turn_span: TraceSpan,
    ) -> SupportResponse:
        try:
            agent = self._answer_agents[routing.intent]
            with self._recorder.span("support_agent.answer") as span:
                model_started_at = perf_counter()
                result = await agent.run(
                    request.message,
                    deps=deps,
                    usage_limits=_ANSWER_USAGE_LIMIT,
                )
                draft = result.output
                if draft is None:
                    raise UnexpectedModelBehavior("Answer agent returned no output")
                usage.add(result.usage)
                span.set_attribute(
                    "model.latency.ms",
                    round((perf_counter() - model_started_at) * 1000, 2),
                )
                span.set_attribute("model.tokens.input", result.usage.input_tokens)
                span.set_attribute("model.tokens.output", result.usage.output_tokens)
                span.set_attribute("model.tokens.total", result.usage.total_tokens)
                if result.usage.cost is not None:
                    span.set_attribute("model.cost.usd", float(result.usage.cost))
                span.set_attribute("model.run.id", result.run_id)
        except Exception:
            turn_span.set_attribute("support.reason.code", ReasonCode.MODEL_ERROR.value)
            return self._failed_response()
        if (
            routing.intent is RouteIntent.REFUND
            and request.refund_confirmed
            and deps.service.pending_proposal(routing.order_id) is not None
            and deps.service.confirmed_refund_for(routing.order_id) is None
            and routing.order_id is not None
        ):
            await deps.service.confirm_refund(routing.order_id)
        return self._assemble(request, routing, draft, deps)

    def _assemble(
        self,
        request: SupportRequest,
        routing: RoutingDecision,
        draft: AnswerDraft,
        deps: AgentDeps,
    ) -> SupportResponse:
        """This method builds the trusted response from the model draft and service state.

        The service supplies identifiers and state changes.
        The model cannot supply identifiers or state changes.
        """
        service = deps.service
        context = AnswerContext(routing=routing)
        outcome = SupportOutcome.COMPLETED
        reason = ReasonCode.ORDER_STATUS_OK
        message = draft.message

        if draft.intent is RouteIntent.ORDER_STATUS:
            context.order = service.last_order
            if service.last_order is None:
                reason = ReasonCode.ORDER_NOT_FOUND
            elif deps.retry_count > 0:
                reason = ReasonCode.OK_WITH_RETRY
            else:
                reason = ReasonCode.ORDER_STATUS_OK
        elif draft.intent is RouteIntent.POLICY:
            context.policy = service.last_policy
            grounded = (
                service.retrieved_policy_version == ACCEPTED_POLICY_VERSION
                and self._answer_instructions_version == ACCEPTED_ANSWER_INSTRUCTIONS_VERSION
                and "get_policy" in service.tool_calls
            )
            if grounded and service.policy_retriever is not None:
                try:
                    cited = build_cited_policy_answer(
                        draft.message,
                        draft.citations,
                        service.last_policy_hits,
                    )
                except HallucinatedCitation:
                    grounded = False
                else:
                    context.citations = cited.citations
                    message = cited.message
            self._last_grounded = grounded
            if grounded:
                reason = ReasonCode.POLICY_ANSWER
            else:
                outcome = SupportOutcome.BLOCKED
                reason = ReasonCode.POLICY_ANSWER_UNGROUNDED
        elif draft.intent is RouteIntent.REFUND:
            confirmed_order = service.confirmed_refund_for(routing.order_id)
            if confirmed_order is not None:
                context.order = confirmed_order
                reason = ReasonCode.REFUND_CONFIRMED
                message = "Your refund was confirmed and the order is now marked as refunded."
            elif service.pending_proposal(routing.order_id) is not None:
                context.proposal = service.pending_proposal(routing.order_id)
                reason = ReasonCode.REFUND_PROPOSED
            elif service.last_tool_error is not None:
                outcome = SupportOutcome.BLOCKED
                reason = service.last_tool_error
            else:
                outcome = SupportOutcome.BLOCKED
                reason = ReasonCode.REFUND_BLOCKED_UNCONFIRMED
        elif draft.intent is RouteIntent.ESCALATE:
            context.escalation = service.last_escalation
            if context.escalation is None:
                outcome = SupportOutcome.BLOCKED
                reason = ReasonCode.TOOL_ERROR
            else:
                outcome = SupportOutcome.ESCALATED
                reason = ReasonCode.ESCALATED

        return SupportResponse(
            intent=draft.intent,
            outcome=outcome,
            reason_code=reason,
            message=message,
            context=context,
        )

    def _failed_response(self) -> SupportResponse:
        return SupportResponse(
            intent=RouteIntent.ESCALATE,
            outcome=SupportOutcome.FAILED,
            reason_code=ReasonCode.MODEL_ERROR,
            message=(
                "I could not complete your request just now. "
                "A human support agent will follow up with you."
            ),
            context=AnswerContext(
                routing=RoutingDecision(intent=RouteIntent.ESCALATE, confidence=0.0)
            ),
        )


# ----------------------------------------------------------------------
# Tools. Each tool records a sanitized span and returns a short, safe
# summary to the model; full values (policy text, amounts, tokens) are
# only ever returned to the model, never recorded.
# ----------------------------------------------------------------------
async def _get_order_status(ctx: RunContext[AgentDeps], order_id: uuid.UUID) -> str:
    deps = ctx.deps
    with deps.recorder.span("support_agent.tool.get_order_status") as span:
        span.set_attribute("tool.name", "get_order_status")
        span.set_attribute("tool.order.id", str(order_id))
        try:
            order = await deps.service.get_order_status(order_id)
        except OrderNotFound:
            span.set_attribute("tool.error.code", ReasonCode.ORDER_NOT_FOUND.value)
            span.set_error(ReasonCode.ORDER_NOT_FOUND.value)
            return "ORDER_NOT_FOUND: no order with that identifier is visible to this customer."
        except Forbidden:
            span.set_attribute("tool.error.code", ReasonCode.FORBIDDEN.value)
            span.set_error(ReasonCode.FORBIDDEN.value)
            return "FORBIDDEN: this customer cannot access that order."
        except (TimeoutError, ConnectionError) as error:
            _transient_failure(deps, span, error)
        deps.service.record_tool_call("get_order_status")
        _tool_outcome(span, ReasonCode.ORDER_STATUS_OK)
        return f"ORDER {order.id} STATUS {order.status.value}"


async def _get_policy(ctx: RunContext[AgentDeps], slug: str = POLICY_SLUG) -> str:
    deps = ctx.deps
    with deps.recorder.span("support_agent.tool.get_policy") as span:
        span.set_attribute("tool.name", "get_policy")
        try:
            policy = await deps.service.get_policy(slug)
        except PolicyNotFound:
            span.set_attribute("tool.error.code", ReasonCode.TOOL_ERROR.value)
            span.set_error(ReasonCode.TOOL_ERROR.value)
            return "POLICY_NOT_FOUND: no policy document is available; escalate."
        except RetrievalError as error:
            span.set_attribute("tool.error.code", error.code)
            span.set_error(error.code)
            return "POLICY_RETRIEVAL_UNAVAILABLE: policy evidence could not be verified; escalate."
        deps.service.record_tool_call("get_policy")
        _tool_outcome(span, ReasonCode.POLICY_ANSWER)
        if deps.service.policy_retriever is not None:
            evidence = "\n".join(
                f"[{hit.chunk_id}] {hit.text}" for hit in deps.service.last_policy_hits
            )
            return f"POLICY VERSION {policy.version}\n{evidence}"
        return f"POLICY VERSION {policy.version}\n{policy.content}"


async def _propose_refund(ctx: RunContext[AgentDeps], order_id: uuid.UUID, reason: str) -> str:
    deps = ctx.deps
    with deps.recorder.span("support_agent.tool.propose_refund") as span:
        span.set_attribute("tool.name", "propose_refund")
        span.set_attribute("tool.order.id", str(order_id))
        try:
            proposal = await deps.service.propose_refund(order_id, reason)
        except Forbidden:
            span.set_attribute("tool.error.code", ReasonCode.REFUND_BLOCKED_FORBIDDEN.value)
            span.set_error(ReasonCode.REFUND_BLOCKED_FORBIDDEN.value)
            return "REFUND_FORBIDDEN: this customer cannot refund that order."
        except OrderNotFound:
            span.set_attribute("tool.error.code", ReasonCode.ORDER_NOT_FOUND.value)
            span.set_error(ReasonCode.ORDER_NOT_FOUND.value)
            return "ORDER_NOT_FOUND: no order with that identifier is visible to this customer."
        except InvalidTransition:
            span.set_attribute("tool.error.code", ReasonCode.REFUND_BLOCKED_INELIGIBLE.value)
            span.set_error(ReasonCode.REFUND_BLOCKED_INELIGIBLE.value)
            return "REFUND_INELIGIBLE: the order cannot be refunded from its current state."
        except (TimeoutError, ConnectionError) as error:
            _transient_failure(deps, span, error)
        deps.service.record_tool_call("propose_refund")
        _tool_outcome(span, ReasonCode.REFUND_PROPOSED)
        return (
            f"PROPOSAL {proposal.proposal_id} READY for order {proposal.order_id}; "
            f"amount {proposal.amount}; policy version {proposal.policy_version}. "
            "Explicit customer confirmation is required before execution."
        )


async def _confirm_refund(
    ctx: RunContext[AgentDeps],
    order_id: uuid.UUID,
) -> str:
    deps = ctx.deps
    with deps.recorder.span("support_agent.tool.confirm_refund") as span:
        span.set_attribute("tool.name", "confirm_refund")
        span.set_attribute("tool.order.id", str(order_id))
        try:
            order = await deps.service.confirm_refund(order_id)
        except RefundNotConfirmed:
            span.set_attribute("tool.error.code", ReasonCode.REFUND_BLOCKED_UNCONFIRMED.value)
            span.set_error(ReasonCode.REFUND_BLOCKED_UNCONFIRMED.value)
            return (
                "REFUND_NOT_CONFIRMED: there is no matching confirmation for this "
                "order. Propose the refund again or escalate."
            )
        except Forbidden:
            span.set_attribute("tool.error.code", ReasonCode.REFUND_BLOCKED_FORBIDDEN.value)
            span.set_error(ReasonCode.REFUND_BLOCKED_FORBIDDEN.value)
            return "REFUND_FORBIDDEN: this customer cannot refund that order."
        except InvalidTransition:
            span.set_attribute("tool.error.code", ReasonCode.REFUND_BLOCKED_INELIGIBLE.value)
            span.set_error(ReasonCode.REFUND_BLOCKED_INELIGIBLE.value)
            return "REFUND_INELIGIBLE: the order cannot be refunded from its current state."
        except (TimeoutError, ConnectionError) as error:
            _transient_failure(deps, span, error)
        deps.service.record_tool_call("confirm_refund")
        _tool_outcome(span, ReasonCode.REFUND_CONFIRMED)
        return f"REFUND CONFIRMED for order {order.id}; status is now {order.status.value}."


async def _escalate(ctx: RunContext[AgentDeps], subject: str) -> str:
    deps = ctx.deps
    with deps.recorder.span("support_agent.tool.escalate") as span:
        span.set_attribute("tool.name", "escalate")
        try:
            ticket = await deps.service.escalate(subject[:200])
        except (TimeoutError, ConnectionError) as error:
            _transient_failure(deps, span, error)
        deps.service.record_tool_call("escalate")
        span.set_attribute("escalation.ticket.id", str(ticket.id))
        _tool_outcome(span, ReasonCode.ESCALATED)
        return f"ESCALATED: support ticket {ticket.id} was created."
