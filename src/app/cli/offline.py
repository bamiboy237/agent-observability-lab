"""This module provides the deterministic model substitute for offline workflows.

The offline workflow must complete without hosted-model or observability
credentials. This module replaces only the hosted-model boundary with a
deterministic plan per scenario: routing decision, ordered tool calls, and
final answer. The agent, services, repository, and database path stay real.
The plans reproduce the eight reference scenarios with the same approved
fault scripts that their evidence describes.
"""

import json
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai import ModelResponse
from pydantic_ai.messages import ModelMessage, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from app.domain.simulation.faults import FaultKind, FaultScript, FaultScriptEntry
from app.domain.simulation.scenarios import NOT_FOUND_ORDER
from app.domain.simulation.schemas import SimulationState

OFFLINE_MODEL_NAME = "gpt-5.2"
OFFLINE_CANDIDATE_MODEL_NAME = "gpt-5.3"


@dataclass(frozen=True)
class OfflineToolCall:
    """This class stores one planned tool call for the offline model."""

    tool: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class OfflinePlan:
    """This class stores one deterministic model behavior for a scenario."""

    routing: dict[str, object]
    tool_calls: tuple[OfflineToolCall, ...] = ()
    answer: dict[str, object] | None = None
    cost: float = 0.001


def offline_fault_script(scenario_id: str) -> FaultScript | None:
    """This function returns the approved fault script for one scenario.

    The scripts reproduce the recorded infrastructure failures: one timeout
    for the retry cases, and a timeout plus a repeat delay for the slow
    database case.
    """
    if scenario_id in ("phase2-03-database-timeout", "phase2-06-repeated-step"):
        return FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),),
        )
    if scenario_id == "phase2-07-slow-database":
        return FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(
                FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),
                FaultScriptEntry(
                    kind=FaultKind.DELAY,
                    tool="get_order_status",
                    delay_ms=1100,
                    repeat=True,
                ),
            ),
        )
    return None


def offline_plan(
    scenario_id: str,
    state: SimulationState,
    *,
    side: str = "baseline",
) -> OfflinePlan:
    """This function returns the deterministic plan for one reference scenario.

    The offline proof must show distinct candidate outcomes while changing
    exactly one declared dimension (the model). On the baseline side the
    refund scenario proposes a refund but never confirms it, so the baseline
    fails that reviewed expectation; the candidate fixes it. On the candidate
    side the database-timeout scenario escalates instead of retrying, so the
    candidate regresses there while the baseline reproduced it. Every other
    scenario uses the same reproducing behavior on both sides.
    """
    if side == "candidate" and scenario_id == "phase2-03-database-timeout":
        return OfflinePlan(
            routing={"intent": "escalate", "confidence": 0.8},
            tool_calls=(),
            answer={"intent": "escalate", "message": "A human agent will follow up."},
        )
    if side == "baseline" and scenario_id == "phase2-05-unconfirmed-refund":
        order_id = state.orders[0].id
        return OfflinePlan(
            routing={"intent": "refund", "confidence": 0.9, "order_id": str(order_id)},
            tool_calls=(
                OfflineToolCall("_get_order_status", {"order_id": str(order_id)}),
                OfflineToolCall("_propose_refund", {"order_id": str(order_id)}),
            ),
            answer={"intent": "refund", "message": "Your refund is being processed."},
        )
    if scenario_id == "phase2-01-bad-prompt-policy-answer":
        return OfflinePlan(
            routing={"intent": "policy", "confidence": 0.9, "policy_slug": "refund-and-delivery"},
            tool_calls=(),
            answer={
                "intent": "policy",
                "message": "The policy allows refunds for any order at any time.",
            },
        )
    if scenario_id == "phase2-02-wrong-policy-evidence":
        return OfflinePlan(
            routing={"intent": "policy", "confidence": 0.9, "policy_slug": "refund-and-delivery"},
            tool_calls=(OfflineToolCall("_get_policy", {"slug": "refund-and-delivery"}),),
            answer={
                "intent": "policy",
                "message": "The policy says delivered orders may be returned.",
            },
        )
    if scenario_id == "phase2-04-wrong-tool-arguments":
        return _order_status_plan(NOT_FOUND_ORDER)
    if scenario_id == "phase2-05-unconfirmed-refund":
        order_id = state.orders[0].id
        return OfflinePlan(
            routing={"intent": "refund", "confidence": 0.9, "order_id": str(order_id)},
            tool_calls=(
                OfflineToolCall("_get_order_status", {"order_id": str(order_id)}),
                OfflineToolCall("_confirm_refund", {"order_id": str(order_id)}),
            ),
            answer={"intent": "refund", "message": "Your refund is being processed."},
        )
    if state.orders:
        return _order_status_plan(state.orders[0].id)
    return OfflinePlan(
        routing={"intent": "escalate", "confidence": 0.8},
        tool_calls=(),
        answer={"intent": "escalate", "message": "A human agent will follow up."},
    )


def _order_status_plan(order_id: UUID) -> OfflinePlan:
    return OfflinePlan(
        routing={"intent": "order_status", "confidence": 0.95, "order_id": str(order_id)},
        tool_calls=(OfflineToolCall("_get_order_status", {"order_id": str(order_id)}),),
        answer={"intent": "order_status", "message": "Your order is shipped."},
    )


def build_offline_model(plan: OfflinePlan) -> FunctionModel:
    """This function builds the deterministic model substitute for one plan.

    The first invocation is the routing agent, which has no tools. Later
    invocations belong to the answer agent: the model emits the next planned
    tool call until every planned call returned, then emits the final answer.
    """

    def scripted(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        usage = RequestUsage(input_tokens=12, output_tokens=6, cost=plan.cost)
        if not info.function_tools:
            return ModelResponse(parts=[TextPart(json.dumps(plan.routing))], usage=usage)
        returns = 0
        for message in messages:
            for part in getattr(message, "parts", ()):
                if isinstance(part, ToolReturnPart):
                    returns += 1
        if plan.answer is not None and returns >= len(plan.tool_calls):
            return ModelResponse(parts=[TextPart(json.dumps(plan.answer))], usage=usage)
        call = plan.tool_calls[returns]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=call.tool, args=dict(call.arguments))],
            usage=usage,
        )

    return FunctionModel(scripted, model_name=OFFLINE_MODEL_NAME)


def install_offline_model(plans: dict[str, OfflinePlan]) -> None:
    """This function installs one deterministic model per configured name.

    The plans map a model config name to the behavior it should produce, so
    baseline and candidate runs of a comparison stay deterministic and
    distinguishable only by the declared change.
    """

    def build(config: object) -> FunctionModel:
        name = getattr(config, "name")
        plan = plans.get(name)
        if plan is None:
            raise AssertionError(f"no offline plan for model name {name!r}")
        return build_offline_model(plan)

    import app.adapters.pydantic_ai_agent as agent_module

    agent_module.build_pydantic_ai_model = build


def _scenario_from_message(message: str) -> str:
    """This function maps one request message to its reference scenario.

    The eight approved request messages embed their scenario id (the proof
    compiles them that way), so the deterministic model selects the right
    plan from the observed request text alone. The order-status family
    shares one plan; their bundles carry the faults.
    """
    for scenario_id in (
        "phase2-01-bad-prompt-policy-answer",
        "phase2-02-wrong-policy-evidence",
        "phase2-04-wrong-tool-arguments",
        "phase2-05-unconfirmed-refund",
        "phase2-06-repeated-step",
        "phase2-07-slow-database",
        "phase2-08-model-cost-comparison",
    ):
        if scenario_id in message:
            return scenario_id
    return "phase2-03-database-timeout"


def _answer_scripted(
    plan: OfflinePlan,
    messages: list[ModelMessage],
    info: AgentInfo,
) -> ModelResponse:
    """This function produces the answer-agent behavior for one plan."""
    usage = RequestUsage(input_tokens=12, output_tokens=6, cost=plan.cost)
    returns = 0
    for message in messages:
        for part in getattr(message, "parts", ()):
            if isinstance(part, ToolReturnPart):
                returns += 1
    if plan.answer is not None and returns >= len(plan.tool_calls):
        return ModelResponse(parts=[TextPart(json.dumps(plan.answer))], usage=usage)
    call = plan.tool_calls[returns]
    return ModelResponse(
        parts=[ToolCallPart(tool_name=call.tool, args=dict(call.arguments))],
        usage=usage,
    )


def install_offline_proof_model(
    plans_by_name: dict[str, dict[str, OfflinePlan]],
) -> None:
    """This function installs the deterministic proof model.

    The proof runs all eight scenarios once with the baseline model name and
    once with the candidate model name. Each model selects its plan from the
    observed request message, so every scenario gets its own behavior while
    the only declared difference between the two models stays the model
    name.
    """

    plan_cost = next(
        iter(next(iter(plans_by_name.values())).values())
    ).cost

    def build(config: object) -> FunctionModel:
        name = str(getattr(config, "name"))
        plans = plans_by_name[name]
        selected: dict[str, OfflinePlan] = {}

        def scripted(
            messages: list[ModelMessage],
            info: AgentInfo,
        ) -> ModelResponse:
            usage = RequestUsage(input_tokens=12, output_tokens=6, cost=plan_cost)
            if not info.function_tools:
                text = ""
                for message in messages:
                    for part in getattr(message, "parts", ()):
                        content = getattr(part, "content", None)
                        if isinstance(content, str):
                            text += content
                scenario = _scenario_from_message(text)
                chosen = plans.get(scenario) or next(iter(plans.values()))
                selected["plan"] = chosen
                return ModelResponse(
                    parts=[TextPart(json.dumps(chosen.routing))], usage=usage
                )
            chosen = selected.get("plan") or next(iter(plans.values()))
            return _answer_scripted(chosen, messages, info)

        return FunctionModel(scripted, model_name=name)

    import app.adapters.pydantic_ai_agent as agent_module

    agent_module.build_pydantic_ai_model = build
