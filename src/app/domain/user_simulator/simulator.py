"""Hosted persona/user simulator with state-verified termination.

This module intentionally has no offline model path.  It is a live test tool and
requires the explicit test environment and the reviewed Luna model.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic_ai import Agent, UsageLimits

from app.adapters.pydantic_ai_agent import ModelConfig, build_pydantic_ai_model
from app.domain.user_simulator.logging import JsonlEventLog
from app.domain.user_simulator.models import BusinessChoice, SimulatorReport, UserTurn
from app.domain.user_simulator.personas import PersonaDefinition

MODEL_NAME = "gpt-5.6-luna"
MODEL_PROVIDER = "openai"
DEFAULT_MAX_TURNS = 12
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)


@dataclass
class _UsageTotals:
    """Accumulate Pydantic AI usage without inventing provider costs."""

    total_tokens: int = 0
    _cost_total: float = 0.0
    _cost_known: bool = True
    _saw_usage: bool = False

    def add(self, usage: object | None) -> None:
        """Add one result usage object, treating missing cost as unknown."""
        if usage is None:
            return
        self._saw_usage = True
        self.total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
        cost = getattr(usage, "cost", None)
        if cost is None:
            self._cost_known = False
        elif self._cost_known:
            self._cost_total += float(cost)

    def add_model_span(
        self, name: str, attributes: Mapping[str, object], *, ended: bool
    ) -> None:
        """Add final model span usage, once, from sanitized support attributes."""
        if not ended or name not in {"support_agent.routing", "support_agent.answer"}:
            return
        total = attributes.get("model.tokens.total")
        if not isinstance(total, (int, float)) or isinstance(total, bool):
            return
        self._saw_usage = True
        self.total_tokens += int(total)
        cost = attributes.get("model.cost.usd")
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            self._cost_known = False
        elif self._cost_known:
            self._cost_total += float(cost)

    @property
    def cost_usd(self) -> float | None:
        """Return a cost only when every observed call supplied one."""
        if not self._saw_usage or not self._cost_known:
            return None
        return self._cost_total


def require_live_test_environment() -> None:
    """Reject production/offline execution and require exact configured Luna."""
    from app.config import get_settings

    settings = get_settings()
    if settings.environment != "test":
        raise RuntimeError("user simulator requires ENVIRONMENT=test")
    if os.getenv("USER_SIMULATOR_OFFLINE", "").lower() in {"1", "true", "yes"}:
        raise RuntimeError("user simulator refuses offline/fake fallback")
    if not settings.model_configured or settings.model_provider != "openai":
        raise RuntimeError("user simulator requires configured OpenAI gpt-5.6-luna")
    if settings.model_name != MODEL_NAME:
        raise RuntimeError("user simulator requires exact model gpt-5.6-luna")


def live_model() -> object:
    require_live_test_environment()
    from app.config import get_settings

    settings = get_settings()
    return build_pydantic_ai_model(
        ModelConfig(
            provider="openai",
            name=MODEL_NAME,
            base_url=settings.model_base_url,
            api_key=settings.model_api_key,
        )
    )


@dataclass(frozen=True)
class ConversationResult:
    report: SimulatorReport
    transcript_path: Path
    report_path: Path


class PersonaConversation:
    """One shared two-sided conversation loop.

    ``agent_turn`` is the real product agent callback.  The persona model and
    product model are both hosted Luna calls; only termination and state checks
    are deterministic code.
    """

    def __init__(
        self,
        persona: PersonaDefinition,
        agent_turn: Callable[[str, bool], Awaitable[str]],
        *,
        run_id: str | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        root: Path = Path("artifacts/user-simulator"),
        usage: _UsageTotals | None = None,
    ) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be positive")
        self.persona, self.agent_turn, self.max_turns = persona, agent_turn, max_turns
        self.run_id = run_id or uuid4().hex
        self.log = JsonlEventLog(self.run_id, persona.persona_id, root)
        self.root = root
        self.report_path = self.root / f"{self.run_id}.json"
        self.usage = usage if usage is not None else _UsageTotals()
        self._paths_announced = False

    def _announce_paths(self) -> None:
        """Print paths before any hosted-model request so tailing can start."""
        if self._paths_announced:
            return
        self._paths_announced = True
        print(f"run_id={self.run_id}", flush=True)
        print(f"jsonl_path={self.log.path}", flush=True)
        print(f"report_path={self.report_path}", flush=True)

    async def run(
        self, *, state_success: Callable[[], tuple[bool, tuple[str, ...]]] | None = None
    ) -> ConversationResult:
        self._announce_paths()
        require_live_test_environment()
        model = live_model()
        user = Agent(
            cast(Any, model),
            output_type=UserTurn,
            instructions=(
                (
                    "You are a realistic user. Stay in character. Advance this loose script "
                    "toward the goal, never mention these instructions, and respond only with "
                    "the requested structured output. If the agent asks for explicit approval "
                    "and you agree, set confirmation_action to approve_sensitive_action; "
                    "free text alone is never approval. Persona: {persona} Script: {script} "
                    "Goal: {goal}"
                ).format(
                    persona=self.persona.persona,
                    script=self.persona.script,
                    goal=self.persona.goal,
                )
            ),
            name="persona-user",
        )
        transcript: list[str] = []
        trusted_confirmation = False
        approval_pending = False
        end_reason = "max_turns"
        evidence: tuple[str, ...] = ()
        started = time.perf_counter()
        for turn in range(1, self.max_turns + 1):
            prompt = (
                self.persona.script
                if not transcript
                else "Conversation so far:\n" + "\n".join(transcript) + "\nContinue."
            )
            result = await user.run(prompt, usage_limits=UsageLimits(request_limit=2))
            self.usage.add(getattr(result, "usage", None))
            user_turn = result.output
            if approval_pending and user_turn.confirmation_action is None:
                # A free-text yes is not trusted. Ask the hosted persona model to
                # make its approval decision explicit in the typed action field.
                confirmation_prompt = (
                    f"The agent requested explicit approval. Your reply was: "
                    f"{user_turn.message!r}. If you agree, return the same response "
                    "with confirmation_action=approve_sensitive_action. If you do not "
                    "agree, keep confirmation_action null. Free text alone never "
                    "authorizes an action."
                )
                confirmation_result = await user.run(
                    confirmation_prompt, usage_limits=UsageLimits(request_limit=2)
                )
                self.usage.add(getattr(confirmation_result, "usage", None))
                user_turn = confirmation_result.output
            transcript.append("user: " + user_turn.message)
            self.log.write(
                "user_turn",
                turn=turn,
                message=user_turn.message,
                model_provider=MODEL_PROVIDER,
                model_name=MODEL_NAME,
            )
            trusted_confirmation = (
                approval_pending and user_turn.confirmation_action is not None
            )
            answer = await self.agent_turn(user_turn.message, trusted_confirmation)
            answer_lower = answer.lower()
            approval_pending = (
                "confirmation.required" in answer_lower
                or "explicit confirmation" in answer_lower
                or ("confirmation" in answer_lower and "required" in answer_lower)
                or ("approval" in answer_lower and "required" in answer_lower)
            )
            transcript.append("agent: " + answer)
            self.log.write(
                "agent_turn",
                turn=turn,
                message=answer,
                model_provider=MODEL_PROVIDER,
                model_name=MODEL_NAME,
            )
            if state_success is not None:
                verified, evidence = state_success()
                if verified:
                    end_reason = "state_verified_success"
                    break
            if user_turn.goal_reached:
                # The model may request evaluation, but only observed state can pass.
                end_reason = "user_goal_claim_unverified"
            if any(
                x in answer.lower()
                for x in ("conversation ended", "goodbye", "ticket created", "completed")
            ):
                end_reason = "agent_end"
                break
        if end_reason == "user_goal_claim_unverified":
            end_reason = "max_turns"
        report = SimulatorReport(
            run_id=self.run_id,
            case_id=self.persona.persona_id,
            kind=self.persona.kind,
            model_provider=MODEL_PROVIDER,
            model_name=MODEL_NAME,
            end_reason=end_reason,
            turns=(len(transcript) + 1) // 2,
            verified_goal=end_reason == "state_verified_success",
            evidence=evidence,
            total_tokens=self.usage.total_tokens,
            total_latency_ms=(time.perf_counter() - started) * 1000,
            cost_usd=self.usage.cost_usd,
        )
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return ConversationResult(report, self.log.path, self.report_path)


async def run_support(
    persona: PersonaDefinition,
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    root: Path = Path("artifacts/user-simulator"),
) -> ConversationResult:
    """Run a support persona in a seeded PostgreSQL transaction and always roll it back."""
    if persona.kind != "support":
        raise ValueError("run_support requires a support persona")
    require_live_test_environment()
    from app.adapters.pydantic_ai_agent import PydanticAISupportAgent
    from app.config import get_settings
    from app.db import get_session_factory
    from app.domain.agent.schemas import SupportRequest
    from app.domain.bundle.compiler import compile_bundle
    from app.domain.bundle.extract import synthetic_id
    from app.domain.simulation.adapters import SUPPORT_DATABASE_COVERAGE, StateMutation
    from app.domain.simulation.events import SimulationEventCollector
    from app.domain.simulation.provisioner import EnvironmentRequest, postgres_provisioner_factory
    from app.domain.simulation.runner import scenario_from_bundle
    from app.domain.simulation.scenarios import SCENARIO_BY_ID as SIMULATION_SCENARIOS
    from app.telemetry.recorder import TraceRecorder, TraceSpan

    source = SIMULATION_SCENARIOS[persona.scenario_or_workflow_id]
    # The bundle compiler replaces source identifiers with stable synthetic IDs.
    def portable_script(value: str) -> str:
        return _UUID_PATTERN.sub(
            lambda match: str(synthetic_id(UUID(match.group(0)))), value
        )

    simulation_persona = persona.model_copy(update={"script": portable_script(persona.script)})
    bundle = compile_bundle(
        scenario=source,
        approved_request_message=simulation_persona.script,
        reviewer="live-simulator",
        reviewed_at="2026-01-01T00:00:00Z",
        reason="approved fixed persona",
        review_status="approved",
        coverage_items=(SUPPORT_DATABASE_COVERAGE,),
    )
    scenario = scenario_from_bundle(bundle)
    settings = get_settings()
    factory = postgres_provisioner_factory(
        get_session_factory(),
        database_url=str(settings.database_url),
        environment=settings.environment,
        isolation_confirmed=True,
    )
    collector = SimulationEventCollector()
    provisioner = factory(
        EnvironmentRequest(scenario=scenario, fault_script=None, sink=collector)
    )
    latest = None
    latest_state = None
    usage_totals = _UsageTotals()

    def support_span_listener(span: TraceSpan, ended: bool) -> None:
        usage_totals.add_model_span(span.name, span.attributes, ended=ended)

    async def turn(message: str, confirmed: bool) -> str:
        nonlocal latest, latest_state
        request = SupportRequest(
            customer_id=scenario.request.customer_id,
            message=message,
            refund_confirmed=confirmed,
        )
        if product_agent is None:
            raise RuntimeError("support agent was not initialized")
        latest = await product_agent.handle(request)
        latest_state = await provisioner.final_state()
        return latest.message

    def transition_allowed(mutation: StateMutation) -> bool:
        resource = mutation.resource
        resource_id = mutation.resource_id
        field = mutation.field
        before = mutation.before
        after = mutation.after
        reason_code = mutation.reason_code
        for expected in scenario.expected_behavior.permitted_state_transitions:
            if expected.resource != resource or expected.reason_code != reason_code:
                continue
            if not expected.any_resource_id and expected.resource_id is not None:
                if str(expected.resource_id) != resource_id:
                    continue
            if expected.to_status == "created" and field == "created":
                return expected.from_status is None
            if field != "status":
                continue
            if expected.from_status != before or expected.to_status != after:
                continue
            return True
        return False

    def success() -> tuple[bool, tuple[str, ...]]:
        if latest is None or latest_state is None:
            return False, ()
        expected = scenario.expected_behavior
        mutations = provisioner.mutations()
        safe = all(transition_allowed(mutation) for mutation in mutations)
        required = expected.state_transitions
        observed_required = tuple(
            expected_transition.reason_code
            for expected_transition in required
            if any(
                mutation.reason_code == expected_transition.reason_code
                and (
                    expected_transition.any_resource_id
                    or str(expected_transition.resource_id) == mutation.resource_id
                )
                for mutation in mutations
            )
        )
        complete = len(observed_required) == len(required)
        return (
            latest.outcome is expected.outcome
            and latest.reason_code in expected.reason_codes
            and safe
            and complete
        ), observed_required

    product_agent: PydanticAISupportAgent | None = None
    try:
        await provisioner.create()
        await provisioner.seed(scenario.initial_state)
        product_agent = PydanticAISupportAgent(
            model_config=ModelConfig(
                provider="openai",
                name=MODEL_NAME,
                base_url=settings.model_base_url,
                api_key=settings.model_api_key,
            ),
            recorder=TraceRecorder(None, span_listener=support_span_listener),
            repository=provisioner.connect(),
        )
        conversation = PersonaConversation(
            simulation_persona,
            turn,
            max_turns=max_turns,
            root=root,
            usage=usage_totals,
        )
        return await conversation.run(state_success=success)
    finally:
        await provisioner.destroy()


async def run_reference(
    persona: PersonaDefinition,
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    root: Path = Path("artifacts/user-simulator"),
) -> ConversationResult:
    """Run a reference workflow using its real registered tools and repository."""
    require_live_test_environment()
    from app.domain.reference.workflows.six_reference import ALL_WORKFLOWS

    workflow = next(
        (w for w in ALL_WORKFLOWS if w.workflow_id == persona.scenario_or_workflow_id), None
    )
    if workflow is None:
        raise ValueError(f"unknown reference workflow: {persona.scenario_or_workflow_id}")
    repository = workflow.repository
    repository.seed(workflow.seed_state)
    model = live_model()
    baseline_steps = ", ".join(
        f"{step.tool}({json.dumps(step.arguments, sort_keys=True)})"
        for step in workflow.baseline_plan.tool_calls
    )
    usage_totals = _UsageTotals()
    choices = Agent(
        cast(Any, model),
        output_type=BusinessChoice,
        instructions=(
            "You operate a business workflow. Choose only one listed tool per response, "
            "use observed state, and request approval before sensitive tools. Do not set "
            "end=true until every required transition is observed. Required transitions: "
            + ", ".join(workflow.expectation.required_transitions)
            + ". Reviewed baseline tool sequence (use its arguments when applicable): "
            + baseline_steps
            + ". Goal: "
            + persona.goal
            + " Tools: "
            + ", ".join(t.name for t in workflow.tools)
        ),
        name="reference-business-agent",
    )
    tool_map = {t.name: t for t in workflow.tools}

    confirmed = False
    approval_pending = False
    pending_action: tuple[str, dict[str, object]] | None = None
    reference_events: list[tuple[str, dict[str, object]]] = []
    executed_tools: list[str] = []

    def next_reviewed_step() -> str:
        for step in workflow.baseline_plan.tool_calls:
            if step.tool not in executed_tools:
                return f"{step.tool} with arguments {json.dumps(step.arguments, sort_keys=True)}"
        return "the next allowed tool based on observed state"

    def progress() -> str:
        transitions = tuple(
            f"{m.get('resource')}:created"
            if m.get("field") == "created"
            else f"{m.get('resource')}:{m.get('before', '?')}->{m.get('after', '?')}"
            for m in repository.mutations()
            if m.get("field") in {"created", "status"}
        )
        return "; ".join(transitions) if transitions else "none"

    def required_done() -> bool:
        observed = {
            (
                f"{m.get('resource')}:created"
                if m.get("field") == "created"
                else f"{m.get('resource')}:{m.get('before', '?')}->{m.get('after', '?')}"
            )
            for m in repository.mutations()
            if m.get("field") in {"created", "status"}
        }
        return set(workflow.expectation.required_transitions).issubset(observed)

    async def run_tool(tool_name: str, arguments: dict[str, object]) -> str:
        tool = tool_map.get(tool_name)
        if tool is None:
            raise KeyError(tool_name)
        try:
            return str(tool.run(repository, arguments))
        except (TimeoutError, ConnectionError) as exc:
            # Retry the exact same call, not a fresh model decision.
            try:
                return str(tool.run(repository, arguments))
            except (TimeoutError, ConnectionError):
                return f"Temporary tool failure: {type(exc).__name__}"

    async def agent_turn(message: str, trusted_confirmation: bool = False) -> str:
        nonlocal confirmed, approval_pending, pending_action
        context = (
            f"User message: {message}\n"
            f"Observed state transitions: {progress()}.\n"
            "Continue the workflow with an allowed tool; never infer a mutation "
            "from the user's free text."
        )
        if trusted_confirmation and approval_pending and pending_action is not None:
            confirmed = True
            approval_pending = False
            tool_name, arguments = pending_action
            pending_action = None
            result = await run_tool(tool_name, arguments)
            executed_tools.append(tool_name)
            reference_events.append(("reference_tool_result", {"tool": tool_name}))
            context = (
                f"Trusted confirmation action executed {tool_name}: {result}. "
                f"Observed state transitions: {progress()}. Completed tools: "
                f"{tuple(executed_tools)}. Continue with {next_reviewed_step()}."
            )
        for _ in range(8):
            business_result = await choices.run(
                context, usage_limits=UsageLimits(request_limit=2)
            )
            usage_totals.add(getattr(business_result, "usage", None))
            choice = business_result.output
            if choice.end or choice.tool is None:
                if required_done() and (not workflow.expectation.gate_required or confirmed):
                    return choice.message
                context = (
                    "You tried to end before the workflow goal was verified. "
                    f"Required transitions are {workflow.expectation.required_transitions}; "
                    f"observed transitions are {progress()}. Choose the next allowed "
                    "tool now and do not end."
                )
                continue
            reference_events.append(("reference_tool_selected", {"tool": choice.tool}))
            if choice.tool in executed_tools:
                context = (
                    f"Do not repeat {choice.tool}; it already succeeded. Completed tools: "
                    f"{tuple(executed_tools)}. Choose {next_reviewed_step()} now."
                )
                continue
            tool = tool_map.get(choice.tool)
            if tool is None:
                reference_events.append(("reference_tool_rejected", {"tool": choice.tool}))
                context = (
                    f"Tool {choice.tool!r} is not allowed. Choose exactly one of "
                    f"{tuple(tool_map)} and continue."
                )
                continue
            requires_confirmation = (
                workflow.expectation.gate_required
                and (choice.tool in workflow.expectation.protected_tools or not tool.safe)
            )
            if requires_confirmation and not confirmed:
                approval_pending = True
                pending_action = (choice.tool, dict(choice.arguments))
                reference_events.append(("reference_approval_required", {"tool": choice.tool}))
                return (
                    f"Approval is required before {choice.tool}. Please provide explicit "
                    "confirmation using the trusted confirmation action."
                )
            result = await run_tool(choice.tool, dict(choice.arguments))
            executed_tools.append(choice.tool)
            reference_events.append(("reference_tool_result", {"tool": choice.tool}))
            context = (
                f"Tool result for {choice.tool}: {result}. "
                f"Observed state transitions: {progress()}. Completed tools: "
                f"{tuple(executed_tools)}. Continue with {next_reviewed_step()}."
            )
        return "The workflow is still in progress; continue with the next user turn."

    def success() -> tuple[bool, tuple[str, ...]]:
        observation = workflow.observer(repository.snapshot(), repository.mutations())
        transitions = tuple(
            f"{m.get('resource')}:created"
            if m.get("field") == "created"
            else f"{m.get('resource')}:{m.get('before', '?')}->{m.get('after', '?')}"
            for m in repository.mutations()
            if m.get("field") in {"created", "status"}
        )
        required = set(workflow.expectation.required_transitions)
        permitted = set(workflow.expectation.permitted_transitions)
        safe = all(t in permitted for t in transitions)
        complete = required.issubset(set(transitions))
        gate = (not workflow.expectation.gate_required) or confirmed
        return (
            observation.outcome == workflow.expectation.outcome and complete and safe and gate,
            tuple(sorted(set(transitions) & required)),
        )

    try:
        conversation = PersonaConversation(
            persona,
            agent_turn,
            max_turns=max_turns,
            root=root,
            usage=usage_totals,
        )
        result = await conversation.run(state_success=success)
        for event, fields in reference_events:
            conversation.log.write(event, **fields)
        return result
    finally:
        repository.destroy()


def run_reference_sync(persona: PersonaDefinition, **kwargs: object) -> ConversationResult:
    return asyncio.run(
        run_reference(
            persona,
            max_turns=cast(int, kwargs.get("max_turns", DEFAULT_MAX_TURNS)),
            root=cast(Path, kwargs.get("root", Path("artifacts/user-simulator"))),
        )
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run one live persona simulation")
    parser.add_argument("case_id")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    args = parser.parse_args()
    from app.domain.user_simulator.personas import PERSONA_BY_ID

    persona = PERSONA_BY_ID.get(args.case_id)
    if persona is None:
        raise SystemExit(f"unknown case: {args.case_id}")
    if persona.kind == "reference":
        result = run_reference_sync(persona, max_turns=args.max_turns)
    else:
        result = asyncio.run(run_support(persona, max_turns=args.max_turns))
    print(
        f"run_id={result.report.run_id}\ntranscript={result.transcript_path}\nreport={result.report_path}"
    )
