"""Focused tests for the hosted persona simulator contract."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from app.domain.user_simulator import simulator
from app.domain.user_simulator.events import EventKind, EventSource, SimulationEvent
from app.domain.user_simulator.models import BusinessChoice, SimulatorReport, UserTurn
from app.domain.user_simulator.personas import (
    PERSONA_BY_ID,
    REFERENCE_PERSONAS,
    SUPPORT_PERSONAS,
)


class FakePersonaAgent:
    """Small fake for the hosted persona-model boundary only."""

    outputs: list[UserTurn] = []
    usages: list[object | None] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        del prompt, kwargs
        usage = self.usages.pop(0) if self.usages else None
        return SimpleNamespace(output=self.outputs.pop(0), usage=usage)


class FakeSettings:
    environment = "test"
    model_configured = True
    model_provider = "openai"
    model_name = "gpt-5.6-luna"


def _install_persona_model(
    monkeypatch: pytest.MonkeyPatch,
    outputs: list[UserTurn],
    usages: list[object | None] | None = None,
) -> None:
    FakePersonaAgent.outputs = list(outputs)
    FakePersonaAgent.usages = list(usages or [])
    monkeypatch.setattr(simulator, "Agent", FakePersonaAgent)
    monkeypatch.setattr(simulator, "live_model", lambda: object())
    monkeypatch.setattr(simulator, "require_live_test_environment", lambda: None)


def test_catalog_has_eight_support_and_seven_reference_personas() -> None:
    assert len(SUPPORT_PERSONAS) == 8
    assert len(REFERENCE_PERSONAS) == 7
    assert len(PERSONA_BY_ID) == 15


def test_exact_luna_settings_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.get_settings", lambda: FakeSettings())
    monkeypatch.delenv("USER_SIMULATOR_OFFLINE", raising=False)
    simulator.require_live_test_environment()
    assert simulator.MODEL_NAME == "gpt-5.6-luna"


def test_model_http_failure_reason_keeps_only_the_status_code() -> None:
    error = ModelHTTPError(429, "gpt-5.6-luna", {"error": "private provider response"})

    assert simulator._safe_failure_reason(error) == "http_429"


def test_non_http_failure_reason_is_the_exception_type() -> None:
    assert simulator._safe_failure_reason(RuntimeError("private detail")) == "RuntimeError"


def test_unconfigured_model_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = FakeSettings()
    settings.model_configured = False
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="model API key"):
        simulator.require_live_test_environment()


class _CaptureSink:
    """Records display events for order/kind assertions."""

    def __init__(self) -> None:
        self.events: list[SimulationEvent] = []

    def emit(self, event: SimulationEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_start_event_announces_paths_before_the_hosted_model_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    persona = SUPPORT_PERSONAS[0]
    _install_persona_model(monkeypatch, [UserTurn(message="Please check it")])
    monkeypatch.setattr(simulator, "live_model", lambda: events.append("model") or object())
    capture = _CaptureSink()
    conversation = simulator.PersonaConversation(
        persona,
        lambda message, confirmed: _answer(message),
        max_turns=1,
        run_id="early",
        root=tmp_path,
    )
    conversation.events.add(capture)
    result = await conversation.run(state_success=lambda: (False, ()))
    first = capture.events[0]
    assert first.display is not None
    assert first.display.kind is EventKind.START
    assert first.display.detail == (
        "run_id=early",
        f"jsonl_path={tmp_path / 'early.jsonl'}",
        f"report_path={tmp_path / 'early.json'}",
    )
    # The model is only called after the START event announced the paths.
    assert events == ["model"]
    assert result.report.run_id == "early"


@pytest.mark.asyncio
async def test_persona_usage_is_aggregated_and_unknown_cost_stays_null(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    persona = SUPPORT_PERSONAS[0]
    usage = SimpleNamespace(total_tokens=17, cost=None)
    _install_persona_model(monkeypatch, [UserTurn(message="Please check it")], usages=[usage])
    result = await simulator.PersonaConversation(
        persona,
        lambda message, confirmed: _answer(message),
        max_turns=1,
        run_id="usage",
        root=tmp_path,
    ).run(state_success=lambda: (False, ()))
    assert result.report.total_tokens == 17
    assert result.report.cost_usd is None


@pytest.mark.asyncio
async def test_model_user_and_agent_events_share_the_same_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    persona = SUPPORT_PERSONAS[0]
    _install_persona_model(
        monkeypatch,
        [UserTurn(message="Please check it")],
        usages=[SimpleNamespace(total_tokens=17)],
    )
    capture = _CaptureSink()
    conversation = simulator.PersonaConversation(
        persona,
        lambda message, confirmed: _answer(message),
        max_turns=1,
        run_id="turn-link",
        root=tmp_path,
    )
    conversation.events.add(capture)

    await conversation.run(state_success=lambda: (False, ()))

    turn_by_kind = {
        event.display.kind: dict(event.persistent.fields).get("turn")
        for event in capture.events
        if event.display is not None
        and event.display.kind in {EventKind.MODEL, EventKind.USER, EventKind.AGENT}
    }
    assert turn_by_kind == {
        EventKind.MODEL: 1,
        EventKind.USER: 1,
        EventKind.AGENT: 1,
    }


@pytest.mark.asyncio
async def test_only_observed_state_can_verify_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    persona = SUPPORT_PERSONAS[0]
    _install_persona_model(monkeypatch, [UserTurn(message="Please check it", goal_reached=True)])
    calls: list[bool] = []

    async def product(message: str, trusted_confirmation: bool) -> str:
        del message
        calls.append(trusted_confirmation)
        return "The request is complete."

    result = await simulator.PersonaConversation(
        persona, product, run_id="observed", root=tmp_path
    ).run(state_success=lambda: (True, ("observed:success",)))
    assert result.report.verified_goal is True
    assert result.report.end_reason == "state_verified_success"
    assert calls == [False]


@pytest.mark.asyncio
async def test_persona_and_support_span_usage_are_combined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.telemetry.recorder import TraceRecorder

    persona = SUPPORT_PERSONAS[0]
    _install_persona_model(
        monkeypatch,
        [UserTurn(message="Please check it")],
        usages=[SimpleNamespace(total_tokens=5, cost=0.01)],
    )
    usage_totals = simulator._UsageTotals()
    recorder = TraceRecorder(
        None,
        span_listener=lambda span, ended: usage_totals.add_model_span(
            span.name, span.attributes, ended=ended
        ),
    )

    async def product(message: str, confirmed: bool) -> str:
        del message, confirmed
        with recorder.span("support_agent.routing") as span:
            span.set_attribute("model.tokens.total", 11)
            span.set_attribute("model.cost.usd", 0.02)
        with recorder.span("support_agent.answer") as span:
            span.set_attribute("model.tokens.total", 7)
        return "The request is complete."

    result = await simulator.PersonaConversation(
        persona, product, max_turns=1, run_id="support-usage", root=tmp_path, usage=usage_totals
    ).run(state_success=lambda: (False, ()))
    assert result.report.total_tokens == 23
    assert result.report.cost_usd is None


@pytest.mark.asyncio
async def test_max_turns_stops_unverified_claims(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    persona = SUPPORT_PERSONAS[0]
    _install_persona_model(
        monkeypatch,
        [
            UserTurn(message="still waiting", goal_reached=True),
            UserTurn(message="still waiting", goal_reached=True),
        ],
    )
    result = await simulator.PersonaConversation(
        persona,
        lambda message, confirmed: _answer(message),
        max_turns=2,
        run_id="max-turns",
        root=tmp_path,
    ).run(state_success=lambda: (False, ()))
    assert result.report.turns == 2
    assert result.report.end_reason == "max_turns"
    assert result.report.verified_goal is False


async def _answer(message: str) -> str:
    del message
    return "I need more information."


@pytest.mark.asyncio
async def test_confirmation_requires_trusted_action_and_survives_turns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    persona = SUPPORT_PERSONAS[4]
    _install_persona_model(
        monkeypatch,
        [
            UserTurn(message="Please do it"),
            UserTurn(message="Yes", confirmation_action="confirm_refund"),
        ],
    )
    trusted: list[bool] = []

    async def product(message: str, confirmed: bool) -> str:
        del message
        trusted.append(confirmed)
        return (
            "Confirmation is required before this action."
            if not confirmed
            else "The refund is complete."
        )

    result = await simulator.PersonaConversation(
        persona, product, run_id="approval", root=tmp_path
    ).run(state_success=lambda: (trusted == [False, True], ("refund:confirmed",)))
    assert trusted == [False, True]
    assert result.report.verified_goal is True
    assert result.report.turns == 2


def test_persistent_log_never_contains_chat_text(tmp_path: Path) -> None:
    from app.domain.user_simulator.events import (
        EventEmitter,
        EventKind,
        JsonlPersistentSink,
    )

    emitter = EventEmitter("safe", "case", [JsonlPersistentSink("safe", "case", tmp_path)])
    emitter.emit(
        EventKind.USER,
        EventSource.PERSONA,
        text="secret customer email and order data",
        turn=1,
        message="secret customer email and order data",
    )
    contents = (tmp_path / "safe.jsonl").read_text()
    assert "secret customer" not in contents
    # Chat lives only in display memory; even a redacted copy is never written.
    assert "message" not in contents


class _ReferenceTool:
    def __init__(self, name: str, safe: bool, fn: object) -> None:
        self.name = name
        self.safe = safe
        self._fn = fn

    def run(self, repository: object, arguments: dict[str, object]) -> str:
        return self._fn(repository, arguments)  # type: ignore[operator]


class _ReferenceRepository:
    def __init__(self) -> None:
        self.state: dict[str, object] = {}
        self._mutations: list[dict[str, object]] = []
        self.destroyed = False

    def seed(self, state: object) -> None:
        self.state = dict(state)
        self._mutations = []

    def snapshot(self) -> object:
        return dict(self.state)

    def mutations(self) -> tuple[dict[str, object], ...]:
        return tuple(self._mutations)

    def reset(self) -> None:
        self._mutations = []

    def destroy(self) -> None:
        self.destroyed = True


@pytest.mark.asyncio
async def test_reference_retry_approval_and_transition_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.domain.reference.contracts import (
        ReferenceCandidate,
        ReferenceExpectation,
        ReferenceObservation,
        ReferencePlan,
        ReferenceWorkflow,
    )

    repository = _ReferenceRepository()
    calls = 0

    def protected_write(repo: object, arguments: dict[str, object]) -> str:
        nonlocal calls
        del arguments
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary")
        assert isinstance(repo, _ReferenceRepository)
        repo.state["done"] = True
        repo._mutations.append(
            {
                "resource": "item",
                "resource_id": "item-1",
                "field": "status",
                "before": "draft",
                "after": "active",
                "reason_code": "item_activated",
            }
        )
        return "written"

    workflow = ReferenceWorkflow(
        workflow_id="test-workflow",
        name="Test workflow",
        source="unit test",
        seed_state={},
        repository=repository,
        tools=(_ReferenceTool("protected_write", False, protected_write),),
        expectation=ReferenceExpectation(
            outcome="completed",
            reason_codes=("activated",),
            permitted_transitions=("item:draft->active",),
            required_transitions=("item:draft->active",),
            gate_required=True,
            protected_tools=("protected_write",),
        ),
        baseline_plan=ReferencePlan(),
        candidate_plan=ReferencePlan(),
        candidate=ReferenceCandidate(
            name="test", change_type="test", baseline_label="a", candidate_label="b"
        ),
        observer=lambda state, mutations: ReferenceObservation(
            outcome="completed" if state.get("done") else "failed",
            reason_code="activated" if state.get("done") else "missing",
            business_outcome="done",
        ),
    )

    class ReferenceAgent:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.name = kwargs.get("name")

        async def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            del prompt, kwargs
            usage = SimpleNamespace(total_tokens=3, cost=0.01)
            if self.name == "persona-user":
                if not getattr(self, "user_sent", False):
                    self.user_sent = True
                    return SimpleNamespace(output=UserTurn(message="Please do it"), usage=usage)
                return SimpleNamespace(
                    output=UserTurn(message="Yes", confirmation_action="confirm_refund"),
                    usage=usage,
                )
            business_count = getattr(self, "business_count", 0)
            self.business_count = business_count + 1
            from app.domain.user_simulator.models import BusinessChoice

            if business_count < 1:
                return SimpleNamespace(
                    output=BusinessChoice(tool="protected_write", arguments={}, message="write"),
                    usage=usage,
                )
            return SimpleNamespace(output=BusinessChoice(message="done", end=True), usage=usage)

    monkeypatch.setattr(simulator, "Agent", ReferenceAgent)
    monkeypatch.setattr(simulator, "live_model", lambda: object())
    monkeypatch.setattr(simulator, "require_live_test_environment", lambda: None)
    monkeypatch.setattr("app.domain.reference.workflows.six_reference.ALL_WORKFLOWS", (workflow,))
    persona = REFERENCE_PERSONAS[0].model_copy(
        update={
            "scenario_or_workflow_id": "test-workflow",
            "persona_id": "reference-test-workflow",
        }
    )
    result = await simulator.run_reference(persona, max_turns=3, root=tmp_path)
    assert calls == 2
    assert result.report.verified_goal is True
    assert result.report.turns == 2
    assert result.report.total_tokens == 12
    assert result.report.cost_usd == pytest.approx(0.04)
    assert repository.destroyed is True


@pytest.mark.asyncio
async def test_reference_events_are_emitted_immediately_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reference tool/approval/retry/state events stream live, never buffered."""
    from app.domain.reference.contracts import (
        ReferenceCandidate,
        ReferenceExpectation,
        ReferenceObservation,
        ReferencePlan,
        ReferenceWorkflow,
    )

    repository = _ReferenceRepository()
    calls = 0

    def protected_write(repo: object, arguments: dict[str, object]) -> str:
        nonlocal calls
        del arguments
        calls += 1
        if calls == 1:
            raise TimeoutError("temporary")
        assert isinstance(repo, _ReferenceRepository)
        repo.state["done"] = True
        repo._mutations.append(
            {
                "resource": "item",
                "resource_id": "item-1",
                "field": "status",
                "before": "draft",
                "after": "active",
                "reason_code": "item_activated",
            }
        )
        return "written"

    workflow = ReferenceWorkflow(
        workflow_id="event-workflow",
        name="Event workflow",
        source="unit test",
        seed_state={},
        repository=repository,
        tools=(_ReferenceTool("protected_write", False, protected_write),),
        expectation=ReferenceExpectation(
            outcome="completed",
            reason_codes=("activated",),
            permitted_transitions=("item:draft->active",),
            required_transitions=("item:draft->active",),
            gate_required=True,
            protected_tools=("protected_write",),
        ),
        baseline_plan=ReferencePlan(),
        candidate_plan=ReferencePlan(),
        candidate=ReferenceCandidate(
            name="test", change_type="test", baseline_label="a", candidate_label="b"
        ),
        observer=lambda state, mutations: ReferenceObservation(
            outcome="completed" if state.get("done") else "failed",
            reason_code="activated" if state.get("done") else "missing",
            business_outcome="done",
        ),
    )

    class EventReferenceAgent:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.name = kwargs.get("name")

        async def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            del prompt, kwargs
            usage = SimpleNamespace(total_tokens=1, cost=None)
            if self.name == "persona-user":
                if not getattr(self, "user_sent", False):
                    self.user_sent = True
                    return SimpleNamespace(output=UserTurn(message="Please do it"), usage=usage)
                return SimpleNamespace(
                    output=UserTurn(message="Yes", confirmation_action="confirm_refund"),
                    usage=usage,
                )
            business_count = getattr(self, "business_count", 0)
            self.business_count = business_count + 1
            from app.domain.user_simulator.models import BusinessChoice

            if business_count < 1:
                return SimpleNamespace(
                    output=BusinessChoice(tool="protected_write", arguments={}, message="write"),
                    usage=usage,
                )
            return SimpleNamespace(output=BusinessChoice(message="done", end=True), usage=usage)

    monkeypatch.setattr(simulator, "Agent", EventReferenceAgent)
    monkeypatch.setattr(simulator, "live_model", lambda: object())
    monkeypatch.setattr(simulator, "require_live_test_environment", lambda: None)
    monkeypatch.setattr("app.domain.reference.workflows.six_reference.ALL_WORKFLOWS", (workflow,))
    persona = REFERENCE_PERSONAS[0].model_copy(
        update={
            "scenario_or_workflow_id": "event-workflow",
            "persona_id": "reference-event-workflow",
        }
    )
    capture = _CaptureSink()
    result = await simulator.run_reference(persona, max_turns=3, root=tmp_path, event_sink=capture)
    kinds = [event.display.kind for event in capture.events if event.display is not None]
    # Tool selection happens before its result; approval precedes the protected
    # tool; retry is emitted for the transient failure; state and the final
    # cleanup/done boundaries are all part of the live stream.
    assert kinds.index(EventKind.TOOL_SELECTED) < kinds.index(EventKind.TOOL_RESULT)
    assert kinds.index(EventKind.APPROVAL) < kinds.index(EventKind.TOOL_SELECTED)
    assert EventKind.RETRY in kinds
    assert EventKind.STATE in kinds
    assert kinds[-1] is EventKind.DONE
    assert kinds[-2] is EventKind.CLEANUP
    assert EventKind.ERROR not in kinds
    assert result.report.verified_goal is True


@pytest.mark.asyncio
async def test_cancellation_writes_partial_report_and_error_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    persona = SUPPORT_PERSONAS[0]
    _install_persona_model(monkeypatch, [UserTurn(message="Please check it")])
    capture = _CaptureSink()

    async def blocking_turn(message: str, confirmed: bool) -> str:
        del message, confirmed
        await asyncio.Event().wait()  # never returns; the test cancels the run

    conversation = simulator.PersonaConversation(
        persona,
        blocking_turn,
        max_turns=5,
        run_id="cancel",
        root=tmp_path,
    )
    conversation.events.add(capture)
    task = asyncio.create_task(conversation.run(state_success=lambda: (False, ())))
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    report_path = tmp_path / "cancel.json"
    assert report_path.exists()
    partial = json.loads(report_path.read_text())
    assert partial["end_reason"] == "cancelled"
    assert partial["errors"] == ["interrupted by user (Ctrl-C)"]
    kinds = [event.display.kind for event in capture.events if event.display is not None]
    assert EventKind.ERROR in kinds
    assert conversation.last_report is not None
    assert conversation.last_report.end_reason == "cancelled"


# ---------------------------------------------------------------------------
# Release-blocker coverage: persona overrides, renderer isolation, projection
# ---------------------------------------------------------------------------


def _minimal_result(persona: object, *, kind: str, run_id: str = "r1") -> object:
    from types import SimpleNamespace as _S

    return _S(
        report=SimulatorReport(
            run_id=run_id,
            case_id=getattr(persona, "persona_id", "case"),
            kind=kind,
            model_provider="test",
            model_name="test",
            end_reason="max_turns",
            turns=0,
            verified_goal=False,
        ),
        transcript_path=Path("/tmp") / f"{run_id}.jsonl",
        report_path=Path("/tmp") / f"{run_id}.json",
    )


@pytest.mark.asyncio
async def test_builtin_adapters_apply_persona_and_runtime_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wizard/flag overrides reach the built-in adapters, not just the CLI."""
    from app.domain.user_simulator import plugins as plugins_mod
    from app.domain.user_simulator.flows import FlowRunRequest, RuntimeEnvironment

    captured: dict[str, object] = {}

    async def fake_run_support(persona: object, **kwargs: object) -> object:
        captured["support_persona"] = persona
        captured["support_database_url"] = kwargs.get("database_url")
        return _minimal_result(persona, kind="support")

    async def fake_run_reference(persona: object, **kwargs: object) -> object:
        del kwargs
        captured["reference_persona"] = persona
        return _minimal_result(persona, kind="reference")

    monkeypatch.setattr(plugins_mod, "run_support", fake_run_support)
    monkeypatch.setattr(plugins_mod, "run_reference", fake_run_reference)

    support = plugins_mod.support_plugin(SUPPORT_PERSONAS[0])
    request = FlowRunRequest(
        case_id="x",
        persona_context="override persona",
        script="override script",
        goal="override goal",
        runtime=RuntimeEnvironment(database_url="postgresql://lab@127.0.0.1:5433/lab"),
    )
    await support.run(request)
    support_persona = captured["support_persona"]
    assert support_persona.persona == "override persona"  # type: ignore[attr-defined]
    assert support_persona.script == "override script"  # type: ignore[attr-defined]
    assert support_persona.goal == "override goal"  # type: ignore[attr-defined]
    assert captured["support_database_url"] == "postgresql://lab@127.0.0.1:5433/lab"

    reference = plugins_mod.reference_plugin(REFERENCE_PERSONAS[0])
    await reference.run(
        FlowRunRequest(case_id="y", persona_context="rctx", script="rscr", goal="rgoal")
    )
    reference_persona = captured["reference_persona"]
    assert reference_persona.persona == "rctx"  # type: ignore[attr-defined]
    assert reference_persona.script == "rscr"  # type: ignore[attr-defined]
    assert reference_persona.goal == "rgoal"  # type: ignore[attr-defined]


class _FailingRendererSink:
    """A CLI renderer that explodes on USER events."""

    def __init__(self) -> None:
        self.seen: list[SimulationEvent] = []

    def emit(self, event: SimulationEvent) -> None:
        self.seen.append(event)
        if event.display is not None and event.display.kind is EventKind.USER:
            raise RuntimeError("renderer exploded")


def _renderer_workflow(repository: object, tool_result: str) -> object:
    from app.domain.reference.contracts import (
        ReferenceCandidate,
        ReferenceExpectation,
        ReferenceObservation,
        ReferencePlan,
        ReferenceWorkflow,
    )

    def read(repo: object, arguments: dict[str, object]) -> str:
        del repo, arguments
        return tool_result

    return ReferenceWorkflow(
        workflow_id="renderer-flow",
        name="Renderer flow",
        source="unit test",
        seed_state={},
        repository=repository,  # type: ignore[arg-type]
        tools=(_ReferenceTool("read", True, read),),
        expectation=ReferenceExpectation(
            outcome="ok",
            reason_codes=("ok",),
            permitted_transitions=(),
            required_transitions=(),
            gate_required=False,
        ),
        baseline_plan=ReferencePlan(),
        candidate_plan=ReferencePlan(),
        candidate=ReferenceCandidate(
            name="test", change_type="test", baseline_label="a", candidate_label="b"
        ),
        observer=lambda state, mutations: ReferenceObservation(
            outcome="ok", reason_code="ok", business_outcome="ok"
        ),
    )


class _OneTurnAgent:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.name = kwargs.get("name")

    async def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        del prompt, kwargs
        usage = SimpleNamespace(total_tokens=1, cost=None)
        if self.name == "persona-user":
            return SimpleNamespace(output=UserTurn(message="Please do it"), usage=usage)
        return SimpleNamespace(
            output=BusinessChoice(tool="read", arguments={}, message="ok"), usage=usage
        )


def _install_renderer_fixture(monkeypatch: pytest.MonkeyPatch, workflow: object) -> None:
    monkeypatch.setattr(simulator, "Agent", _OneTurnAgent)
    monkeypatch.setattr(simulator, "live_model", lambda: object())
    monkeypatch.setattr(simulator, "require_live_test_environment", lambda: None)
    monkeypatch.setattr("app.domain.reference.workflows.six_reference.ALL_WORKFLOWS", (workflow,))


@pytest.mark.asyncio
async def test_renderer_failure_never_aborts_the_business_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = _ReferenceRepository()
    workflow = _renderer_workflow(repository, "RESULT fine")
    _install_renderer_fixture(monkeypatch, workflow)
    persona = REFERENCE_PERSONAS[0].model_copy(
        update={
            "scenario_or_workflow_id": "renderer-flow",
            "persona_id": "reference-renderer-flow",
        }
    )
    failing = _FailingRendererSink()
    result = await simulator.run_reference(persona, max_turns=2, root=tmp_path, event_sink=failing)
    # The run still completed and the persistent JSONL still reached DONE.
    assert result.report.end_reason == "state_verified_success"
    contents = (tmp_path / f"{result.report.run_id}.jsonl").read_text()
    assert '"event": "done"' in contents
    # The renderer error was noticed once, as a safe persistent event.
    assert '"error": "renderer"' in contents


@pytest.mark.asyncio
async def test_tool_result_secret_never_reaches_display_or_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository = _ReferenceRepository()
    workflow = _renderer_workflow(repository, "SUCCESS secret-token=supersecret-abc123 and more")
    _install_renderer_fixture(monkeypatch, workflow)
    persona = REFERENCE_PERSONAS[0].model_copy(
        update={
            "scenario_or_workflow_id": "renderer-flow",
            "persona_id": "reference-renderer-flow",
        }
    )
    capture = _CaptureSink()
    result = await simulator.run_reference(persona, max_turns=2, root=tmp_path, event_sink=capture)
    display_text = " ".join(
        event.display.text for event in capture.events if event.display is not None
    )
    assert "supersecret-abc123" not in display_text
    assert "(result details hidden)" in display_text  # raw result is projected away
    contents = (tmp_path / f"{result.report.run_id}.jsonl").read_text()
    assert "supersecret-abc123" not in contents
