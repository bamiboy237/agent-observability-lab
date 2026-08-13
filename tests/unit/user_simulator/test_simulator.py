"""Focused tests for the hosted persona simulator contract."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.user_simulator import simulator
from app.domain.user_simulator.models import UserTurn
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


@pytest.mark.parametrize(
    ("environment", "offline", "message"),
    [
        ("production", False, "ENVIRONMENT=test"),
        ("test", True, "offline"),
    ],
)
def test_production_and_offline_modes_are_rejected(
    monkeypatch: pytest.MonkeyPatch, environment: str, offline: bool, message: str
) -> None:
    settings = FakeSettings()
    settings.environment = environment
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setenv("USER_SIMULATOR_OFFLINE", "1" if offline else "0")
    with pytest.raises(RuntimeError, match=message):
        simulator.require_live_test_environment()


@pytest.mark.asyncio
async def test_paths_are_printed_before_the_hosted_model_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    persona = SUPPORT_PERSONAS[0]
    _install_persona_model(
        monkeypatch, [UserTurn(message="Please check it")]
    )
    monkeypatch.setattr(
        simulator, "live_model", lambda: events.append("model") or object()
    )
    original_print = print

    def record_print(*args: object, **kwargs: object) -> None:
        del kwargs
        events.append("print:" + " ".join(str(arg) for arg in args))

    monkeypatch.setattr("builtins.print", record_print)
    result = await simulator.PersonaConversation(
        persona, lambda message, confirmed: _answer(message),
        max_turns=1,
        run_id="early",
        root=tmp_path,
    ).run(state_success=lambda: (False, ()))
    assert events[:4] == [
        "print:run_id=early",
        f"print:jsonl_path={tmp_path / 'early.jsonl'}",
        f"print:report_path={tmp_path / 'early.json'}",
        "model",
    ]
    original_print(result.report.run_id)


@pytest.mark.asyncio
async def test_persona_usage_is_aggregated_and_unknown_cost_stays_null(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    persona = SUPPORT_PERSONAS[0]
    usage = SimpleNamespace(total_tokens=17, cost=None)
    _install_persona_model(
        monkeypatch, [UserTurn(message="Please check it")], usages=[usage]
    )
    result = await simulator.PersonaConversation(
        persona, lambda message, confirmed: _answer(message),
        max_turns=1,
        run_id="usage",
        root=tmp_path,
    ).run(state_success=lambda: (False, ()))
    assert result.report.total_tokens == 17
    assert result.report.cost_usd is None


@pytest.mark.asyncio
async def test_only_observed_state_can_verify_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    persona = SUPPORT_PERSONAS[0]
    _install_persona_model(
        monkeypatch, [UserTurn(message="Please check it", goal_reached=True)]
    )
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
        persona, lambda message, confirmed: _answer(message),
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


def test_logs_redact_conversation_text(tmp_path: Path) -> None:
    from app.domain.user_simulator.logging import JsonlEventLog

    log = JsonlEventLog("safe", "case", tmp_path)
    log.write("user_turn", message="secret customer email and order data", turn=1)
    contents = (tmp_path / "safe.jsonl").read_text()
    assert "secret customer" not in contents
    assert '"message": "[redacted]"' in contents


def test_all_fifteen_scripts_route_to_known_personas() -> None:
    scripts = sorted(Path("scripts").glob("run_user_simulator_*.py"))
    assert len(scripts) == 15
    for script in scripts:
        marker = 'sys.argv[1:1] = ["'
        line = next(line for line in script.read_text().splitlines() if marker in line)
        case_id = line.split(marker, 1)[1].split('"', 1)[0]
        assert case_id in PERSONA_BY_ID


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
                    output=UserTurn(
                        message="Yes", confirmation_action="confirm_refund"
                    ),
                    usage=usage,
                )
            business_count = getattr(self, "business_count", 0)
            self.business_count = business_count + 1
            from app.domain.user_simulator.models import BusinessChoice

            if business_count < 1:
                return SimpleNamespace(
                    output=BusinessChoice(
                        tool="protected_write", arguments={}, message="write"
                    ),
                    usage=usage,
                )
            return SimpleNamespace(
                output=BusinessChoice(message="done", end=True), usage=usage
            )

    monkeypatch.setattr(simulator, "Agent", ReferenceAgent)
    monkeypatch.setattr(simulator, "live_model", lambda: object())
    monkeypatch.setattr(simulator, "require_live_test_environment", lambda: None)
    monkeypatch.setattr(
        "app.domain.reference.workflows.six_reference.ALL_WORKFLOWS", (workflow,)
    )
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
