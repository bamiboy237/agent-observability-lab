"""This module tests the single-bundle simulation runner (checkpoint 6.3).

The runner reconstructs the safe request and synthetic state from one
bundle, provisions a disposable environment, runs the real agent workflow
against the scripted hosted-model boundary, applies approved fixtures and
fault scripts, streams events while the run executes, persists the same
transcript, and destroys or retains the environment. The verdict
distinguishes reproduced behavior, accepted behavior, failed behavior,
unexpected access, and missing coverage, and the runner returns safe typed
errors for invalid bundles, missing coverage, model failures, and cleanup
failures.
"""

import asyncio
from collections.abc import Callable

import pytest
from tests.fakes.provisioner import StatefulSupportProvisioner, stateful_provisioner_factory
from tests.fakes.scripted_model import (
    ScriptedPlan,
    ScriptedToolCall,
    escalate_plan,
    install_scripted_model,
    order_status_plan,
    policy_plan,
    refund_plan,
)

from app.adapters.pydantic_ai_agent import ModelConfig
from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.agent.schemas import ReasonCode, SupportOutcome
from app.domain.bundle.compiler import compile_bundle
from app.domain.bundle.schemas import DependencyFixture
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.errors import (
    InvalidSimulationBundleError,
    ModelRunError,
    RetentionUnavailableError,
    UnsupportedArgumentsError,
)
from app.domain.simulation.events import SimulationEventCollector, SimulationEventKind
from app.domain.simulation.faults import FaultKind, FaultScript, FaultScriptEntry
from app.domain.simulation.provisioner import (
    EnvironmentRequest,
    RetentionRequest,
    SupportEnvironmentProvisioner,
)
from app.domain.simulation.runner import (
    RunVerdict,
    run_bundle,
    scenario_from_bundle,
    state_from_bundle,
)
from app.domain.simulation.scenarios import scenario_with_evidence
from app.domain.simulation.schemas import DependencyCoverageRequirement

MODEL_CONFIG = ModelConfig(provider="openai", name="gpt-5.2")


async def _linked_scenario(scenario_id: str, trace_id: str | None = None):
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(trace_id or scenario_id)
    return scenario_with_evidence(scenario_id, evidence), evidence


COVERAGE_ITEMS = (
    CoverageItem(
        dependency="support.database",
        kind="stateful",
        tools=("get_order_status", "get_policy", "propose_refund", "confirm_refund", "escalate"),
        state_transitions=("order:delivered->refunded", "ticket:created"),
    ),
)

REVIEW = {
    "approved_request_message": "Use the approved synthetic request for this simulation.",
    "reviewer": "alice",
    "reviewed_at": "2026-08-08T00:00:00Z",
    "reason": "Reviewed and approved",
    "review_status": "approved",
}


async def _bundle(scenario_id: str, *, trace_id: str | None = None, **kwargs):
    scenario, evidence = await _linked_scenario(scenario_id, trace_id=trace_id)
    return compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
        **kwargs,
    )


def _provisioner_factory(
    provisioner: StatefulSupportProvisioner,
) -> Callable[[EnvironmentRequest], SupportEnvironmentProvisioner]:
    return lambda request: provisioner


async def test_runner_reproduces_order_status_case(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = await _bundle(
        "phase2-08-model-cost-comparison", trace_id="phase2-08-model-cost-comparison-primary"
    )
    state = state_from_bundle(bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))

    collector = SimulationEventCollector()
    provisioner = StatefulSupportProvisioner(
        scenario_from_bundle(bundle),
        event_sink=collector,
    )
    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=_provisioner_factory(provisioner),
        model_config=MODEL_CONFIG,
        collector=collector,
    )

    assert run.verdict is RunVerdict.REPRODUCED
    assert run.response is not None
    assert run.response.outcome is SupportOutcome.COMPLETED
    assert run.response.reason_code is ReasonCode.ORDER_STATUS_OK
    assert run.model_provider == "openai"
    assert run.model_name == "gpt-5.2"
    assert run.total_tokens > 0
    assert run.cost_usd == pytest.approx(0.003, abs=1e-6)
    assert run.bundle_content_hash == bundle.content_hash
    assert run.evidence_ref == bundle.evidence_ref
    assert run.evidence_content_hash == bundle.evidence_content_hash
    assert run.final_state.orders[0].id == state.orders[0].id
    assert provisioner.destroyed is True

    kinds = [event.kind for event in run.events]
    assert SimulationEventKind.ENVIRONMENT_CREATED in kinds
    assert SimulationEventKind.ENVIRONMENT_SEEDED in kinds
    assert kinds.count(SimulationEventKind.MODEL_REQUEST) == 2
    assert kinds.count(SimulationEventKind.MODEL_RESPONSE) == 2
    assert kinds.count(SimulationEventKind.TOOL_SELECTED) == 1
    assert kinds.count(SimulationEventKind.RUN_COMPLETED) == 1
    assert SimulationEventKind.EVALUATOR_RESULT in kinds
    assert run.events[-1].kind is SimulationEventKind.ENVIRONMENT_DESTROYED
    completed = next(e for e in run.events if e.kind is SimulationEventKind.RUN_COMPLETED)
    assert completed.attributes["run.verdict"] == "reproduced"


async def test_runner_streams_the_same_events_live_and_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle(
        "phase2-08-model-cost-comparison", trace_id="phase2-08-model-cost-comparison-primary"
    )
    state = state_from_bundle(bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))

    collector = SimulationEventCollector()
    provisioner = StatefulSupportProvisioner(
        scenario_from_bundle(bundle),
        event_sink=collector,
    )

    async def watch() -> list:
        streamed = []
        async for event in collector.stream():
            streamed.append(event)
            if event.kind is SimulationEventKind.ENVIRONMENT_DESTROYED:
                break
        return streamed

    task = asyncio.create_task(watch())
    await asyncio.sleep(0)
    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=_provisioner_factory(provisioner),
        model_config=MODEL_CONFIG,
        collector=collector,
    )
    streamed = await task
    assert tuple(streamed) == run.events


async def test_runner_reproduces_timeout_with_fault_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle(
        "phase2-03-database-timeout",
        fault_script=FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),),
        ),
    )
    state = state_from_bundle(bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
    )

    assert run.verdict is RunVerdict.REPRODUCED
    assert run.response is not None
    assert run.response.reason_code is ReasonCode.OK_WITH_RETRY
    assert run.retries == 1
    assert run.tool_calls.count("get_order_status") == 2
    kinds = [event.kind for event in run.events]
    assert SimulationEventKind.FAULT_INJECTED in kinds
    assert SimulationEventKind.RETRY in kinds
    fault = next(e for e in run.events if e.kind is SimulationEventKind.FAULT_INJECTED)
    assert fault.attributes["fault.kind"] == "timeout"


async def test_runner_reproduces_slow_database_with_delay_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle(
        "phase2-07-slow-database",
        fault_script=FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(
                FaultScriptEntry(
                    kind=FaultKind.DELAY,
                    tool="get_order_status",
                    delay_ms=1100,
                    repeat=True,
                ),
            ),
        ),
    )
    state = state_from_bundle(bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
    )

    assert run.verdict is RunVerdict.ACCEPTED
    assert run.response is not None
    assert run.response.outcome is SupportOutcome.COMPLETED
    assert run.total_latency_ms is not None and run.total_latency_ms >= 1050
    latency = run.evaluators.result_for("latency")
    assert latency is not None and latency.passed is False
    assert "exceeds" in latency.reason
    fault = next(e for e in run.events if e.kind is SimulationEventKind.FAULT_INJECTED)
    assert fault.attributes["fault.kind"] == "delay"


async def test_runner_reproduces_stale_policy_evidence_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle("phase2-02-wrong-policy-evidence")
    install_scripted_model(monkeypatch, policy_plan())

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
    )

    assert run.verdict is RunVerdict.REPRODUCED
    assert run.response is not None
    assert run.response.outcome is SupportOutcome.BLOCKED
    assert run.response.reason_code is ReasonCode.POLICY_ANSWER_UNGROUNDED
    policy_evidence = run.evaluators.result_for("policy_evidence")
    assert policy_evidence is not None and policy_evidence.passed is True
    assert policy_evidence.measured["retrieved_policy_version"] == "2025-01-01"
    retrieval = next(
        e
        for e in run.events
        if e.kind is SimulationEventKind.DEPENDENCY_RESULT
        and "retrieval.policy.version" in e.attributes
    )
    assert retrieval.attributes["retrieval.policy.version"] == "2025-01-01"


async def test_runner_flags_state_changes_outside_the_permitted_transitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, evidence = await _linked_scenario("phase2-05-unconfirmed-refund")
    scenario = scenario.model_copy(
        update={
            "request": scenario.request.model_copy(update={"refund_confirmed": True}),
            "expected_behavior": scenario.expected_behavior.model_copy(
                update={"permitted_state_transitions": ()}
            ),
            "content_hash": None,
        }
    )
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )
    state = state_from_bundle(bundle)
    install_scripted_model(monkeypatch, refund_plan(state.orders[0].id, confirmed=True))

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
    )

    assert run.mutations
    unexpected = run.evaluators.result_for("unexpected_state_changes")
    assert unexpected is not None and unexpected.passed is False
    assert "refund_executed" in unexpected.measured["unexpected_mutations"]


async def test_runner_reproduces_unconfirmed_refund_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle("phase2-05-unconfirmed-refund")
    state = state_from_bundle(bundle)
    plan = ScriptedPlan(
        routing={"intent": "refund", "confidence": 0.9, "order_id": str(state.orders[0].id)},
        tool_calls=(
            ScriptedToolCall("_get_order_status", {"order_id": str(state.orders[0].id)}),
            ScriptedToolCall("_confirm_refund", {"order_id": str(state.orders[0].id)}),
        ),
        answer={"intent": "refund", "message": "Your refund is being processed."},
    )
    install_scripted_model(monkeypatch, plan)

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
        tools_override=("get_order_status", "confirm_refund", "escalate"),
    )

    assert run.verdict is RunVerdict.REPRODUCED
    assert run.response is not None
    assert run.response.outcome is SupportOutcome.BLOCKED
    assert run.response.reason_code is ReasonCode.REFUND_BLOCKED_UNCONFIRMED
    assert run.mutations == ()
    assert run.final_state.orders[0].status.value == "delivered"
    confirmation = run.evaluators.result_for("refund_confirmation")
    assert confirmation is not None and confirmation.passed is True


async def test_runner_verdict_is_accepted_when_reason_deviates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
        fault_script=FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),),
        ),
    )
    state = state_from_bundle(bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
    )

    assert run.response is not None
    assert run.response.outcome is SupportOutcome.COMPLETED
    assert run.response.reason_code is ReasonCode.OK_WITH_RETRY
    assert run.verdict is RunVerdict.ACCEPTED


async def test_runner_reports_unexpected_access_from_a_rejecting_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle("phase2-01-bad-prompt-policy-answer")
    install_scripted_model(monkeypatch, escalate_plan())

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=stateful_provisioner_factory(
            boundary_error=UnsupportedArgumentsError(
                dependency="support.database",
                tool="escalate",
                arguments={},
            )
        ),
        model_config=MODEL_CONFIG,
    )

    assert run.verdict is RunVerdict.UNEXPECTED_ACCESS
    assert run.response is None
    assert "unexpected_access" in run.errors
    assert run.evaluators.results == ()


async def test_runner_rejects_unreachable_declared_dependency_before_running() -> None:
    scenario, evidence = await _linked_scenario("phase2-01-bad-prompt-policy-answer")
    scenario = scenario.model_copy(
        update={
            "required_dependency_coverage": (
                DependencyCoverageRequirement(
                    dependency="messaging",
                    kind="stateful",
                    tools=("get_order_status",),
                ),
            )
        }
    )
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=(
            CoverageItem(
                dependency="messaging",
                kind="stateful",
                tools=("get_order_status",),
                state_transitions=(),
            ),
        ),
        **REVIEW,
    )

    with pytest.raises(InvalidSimulationBundleError, match="cannot use"):
        await run_bundle(
            bundle=bundle,
            provisioner_factory=stateful_provisioner_factory(),
            model_config=MODEL_CONFIG,
        )


async def test_runner_rejects_unreachable_recorded_fixtures_before_running() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    scenario = scenario.model_copy(
        update={
            "required_dependency_coverage": scenario.required_dependency_coverage
            + (
                DependencyCoverageRequirement(
                    dependency="clock",
                    kind="recorded",
                    tools=("clock.now",),
                ),
            ),
            "content_hash": None,
        }
    )
    fixture = DependencyFixture(
        dependency="clock",
        adapter_name="clock",
        adapter_version="1.0.0",
        tool="clock.now",
        arguments={},
        payload={"now": "2026-08-08T00:00:00Z"},
    )
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS
        + (
            CoverageItem(
                dependency="clock",
                kind="recorded",
                tools=("clock.now",),
                state_transitions=(),
            ),
        ),
        dependency_fixtures=(fixture,),
        **REVIEW,
    )

    with pytest.raises(
        InvalidSimulationBundleError, match="cannot use declared dependency 'clock'"
    ):
        await run_bundle(
            bundle=bundle,
            provisioner_factory=stateful_provisioner_factory(),
            model_config=MODEL_CONFIG,
        )


async def test_runner_rejects_fault_script_for_another_dependency_before_running() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    scenario = scenario.model_copy(
        update={
            "required_dependency_coverage": scenario.required_dependency_coverage
            + (
                DependencyCoverageRequirement(
                    dependency="payments.external",
                    kind="recorded",
                    tools=("get_order_status",),
                ),
            ),
            "content_hash": None,
        }
    )
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS
        + (
            CoverageItem(
                dependency="payments.external",
                kind="recorded",
                tools=("get_order_status",),
                state_transitions=(),
            ),
        ),
        dependency_fixtures=(
            DependencyFixture(
                dependency="payments.external",
                adapter_name="payments.external",
                adapter_version="1.0.0",
                tool="get_order_status",
                arguments={"order_id": "11111111-1111-4111-8111-111111111111"},
                payload={"status": "paid"},
            ),
        ),
        fault_script=FaultScript(
            script_version="1",
            dependency="payments.external",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),),
        ),
        **REVIEW,
    )

    with pytest.raises(InvalidSimulationBundleError, match="fault script targets dependency"):
        await run_bundle(
            bundle=bundle,
            provisioner_factory=stateful_provisioner_factory(),
            model_config=MODEL_CONFIG,
        )


async def test_runner_rejects_recorded_fixtures_for_the_owned_database() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    scenario = scenario.model_copy(
        update={
            "required_dependency_coverage": (
                DependencyCoverageRequirement(
                    dependency="support.database",
                    kind="recorded",
                    tools=("get_order_status",),
                ),
            )
        }
    )
    fixture = DependencyFixture(
        dependency="support.database",
        adapter_name="support.database",
        adapter_version="4.0.0",
        tool="get_order_status",
        arguments={"order_id": "11111111-1111-4111-8111-111111111111"},
        payload={"status": "shipped"},
    )
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=(
            CoverageItem(
                dependency="support.database",
                kind="recorded",
                tools=("get_order_status",),
                state_transitions=(),
            ),
        ),
        dependency_fixtures=(fixture,),
        **REVIEW,
    )

    with pytest.raises(InvalidSimulationBundleError, match="must not replace support.database"):
        await run_bundle(
            bundle=bundle,
            provisioner_factory=stateful_provisioner_factory(),
            model_config=MODEL_CONFIG,
        )


async def test_runner_rejects_retention_until_a_manager_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle(
        "phase2-08-model-cost-comparison", trace_id="phase2-08-model-cost-comparison-primary"
    )
    state = state_from_bundle(bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))

    collector = SimulationEventCollector()
    provisioner = StatefulSupportProvisioner(
        scenario_from_bundle(bundle),
        event_sink=collector,
    )
    with pytest.raises(RetentionUnavailableError, match="no retention manager exists"):
        await run_bundle(
            bundle=bundle,
            provisioner_factory=_provisioner_factory(provisioner),
            model_config=MODEL_CONFIG,
            collector=collector,
            retention=RetentionRequest(reason="review the run", ttl_hours=1),
        )

    assert provisioner.created is False
    assert collector.events() == ()


async def test_runner_cleans_up_and_raises_model_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await _bundle("phase2-01-bad-prompt-policy-answer")
    install_scripted_model(monkeypatch, escalate_plan())

    with pytest.raises(ModelRunError) as excinfo:
        await run_bundle(
            bundle=bundle,
            provisioner_factory=stateful_provisioner_factory(
                boundary_error=RuntimeError("database connection lost")
            ),
            model_config=MODEL_CONFIG,
        )
    assert excinfo.value.code == "model_failure"


async def test_runner_rejects_bundle_without_derived_identity() -> None:
    bundle = await _bundle(
        "phase2-08-model-cost-comparison", trace_id="phase2-08-model-cost-comparison-primary"
    )
    stripped = bundle.model_copy(update={"bundle_id": None, "content_hash": None})

    with pytest.raises(InvalidSimulationBundleError, match="no derived identifier"):
        await run_bundle(
            bundle=stripped,
            provisioner_factory=stateful_provisioner_factory(),
            model_config=MODEL_CONFIG,
        )


def test_state_from_bundle_reconstructs_synthetic_state() -> None:
    bundle = _bundle_sync("phase2-05-unconfirmed-refund")
    state = state_from_bundle(bundle)
    assert len(state.orders) == 1
    order_seed = next(seed for seed in bundle.resource_seeds if seed.resource == "order")
    assert str(state.orders[0].id) == order_seed.records[0]["id"]
    scenario = scenario_from_bundle(bundle)
    assert scenario.request.customer_id == bundle.scenario.request.customer_id
    assert scenario.request.refund_confirmed is False
    assert scenario.expected_behavior == bundle.expected_behavior


def _bundle_sync(scenario_id: str):
    async def build():
        return await _bundle(scenario_id)

    return asyncio.run(build())
