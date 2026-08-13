"""Focused tests for the generic flow registry contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.user_simulator.events import SimulationEvent
from app.domain.user_simulator.flows import (
    FlowMetadata,
    FlowNotFoundError,
    FlowPlugin,
    FlowRegistrationError,
    FlowRegistry,
    FlowRunRequest,
    FlowRunResult,
    ToolProjector,
)
from app.domain.user_simulator.models import SimulatorReport
from app.domain.user_simulator.plugins import (
    REFERENCE_PROJECTOR,
    SUPPORT_PROJECTOR,
    build_default_registry,
    builtin_plugin_factory,
)

_FLOW_ID = "test-flow"


class _RecordingSink:
    """EventSink stub that records what it received."""

    def __init__(self) -> None:
        self.received: list[SimulationEvent] = []

    def emit(self, event: SimulationEvent) -> None:
        self.received.append(event)


class _Plugin:
    """A minimal FlowPlugin implementation for registry tests."""

    def __init__(self, flow_id: str, kind: str = "test") -> None:
        self.metadata = FlowMetadata(
            flow_id=flow_id, case_id=flow_id, kind=kind, name=flow_id
        )
        self.requests: list[FlowRunRequest] = []

    async def run(self, request: FlowRunRequest) -> FlowRunResult:
        self.requests.append(request)
        return FlowRunResult(
            report=SimulatorReport(
                run_id="run-1",
                case_id=request.case_id,
                kind=self.metadata.kind,
                model_provider="test",
                model_name="test",
                end_reason="max_turns",
                turns=0,
                verified_goal=False,
            ),
            transcript_path=request.root / "run-1.jsonl",
            report_path=request.root / "run-1.json",
        )


def test_flow_metadata_and_request_are_typed() -> None:
    from app.domain.user_simulator.flows import RuntimeEnvironment

    metadata = FlowMetadata(flow_id="a", case_id="a", kind="support", name="A")
    request = FlowRunRequest(
        case_id="a",
        max_turns=3,
        root=Path("/tmp"),
        persona_context="custom persona",
        script="custom script",
        goal="custom goal",
        runtime=RuntimeEnvironment(database_url="postgresql://localhost/db"),
    )
    assert metadata.flow_id == "a"
    assert request.max_turns == 3
    assert request.root == Path("/tmp")
    assert request.sink is None
    assert request.persona_context == "custom persona"
    assert request.script == "custom script"
    assert request.goal == "custom goal"
    assert request.runtime is not None
    assert request.runtime.database_url == "postgresql://localhost/db"


@pytest.mark.asyncio
async def test_flow_plugin_protocol_is_structural_and_async() -> None:
    import inspect

    plugin = _Plugin(_FLOW_ID)
    assert isinstance(plugin, FlowPlugin)
    assert inspect.iscoroutinefunction(plugin.run)
    result = await plugin.run(FlowRunRequest(case_id=_FLOW_ID))
    assert result.report.run_id == "run-1"
    assert result.report_path == Path("artifacts/user-simulator") / "run-1.json"


def test_registry_register_get_all_and_len() -> None:
    registry = FlowRegistry()
    registry.register(_Plugin("one"))
    registry.register(_Plugin("two"))
    assert len(registry) == 2
    assert registry.contains("one")
    assert not registry.contains("missing")
    assert {plugin.metadata.flow_id for plugin in registry.all()} == {"one", "two"}
    assert registry.get("two").metadata.flow_id == "two"


def test_registry_rejects_duplicate_flow_ids() -> None:
    registry = FlowRegistry()
    registry.register(_Plugin("dup"))
    with pytest.raises(FlowRegistrationError, match="duplicate flow id: dup"):
        registry.register(_Plugin("dup"))


def test_registry_rejects_plugins_without_metadata() -> None:
    registry = FlowRegistry()

    class NoMetadata:
        def run(self, request: FlowRunRequest) -> FlowRunResult:
            raise AssertionError("unused")

    with pytest.raises(FlowRegistrationError, match="(?i)metadata"):
        registry.register(NoMetadata())  # type: ignore[arg-type]


def test_registry_get_unknown_flow_raises_not_found() -> None:
    registry = FlowRegistry()
    registry.register(_Plugin("known"))
    with pytest.raises(FlowNotFoundError, match="unknown flow: missing"):
        registry.get("missing")


def test_builtin_factory_registers_lazily_and_once() -> None:
    registry = FlowRegistry()
    calls: list[int] = []

    def factory() -> tuple[FlowPlugin, ...]:
        calls.append(1)
        return (_Plugin("builtin-a"), _Plugin("builtin-b"))

    registry.register_builtin(factory)
    assert calls == []  # nothing materialized until first access
    assert len(registry) == 2
    assert calls == [1]
    assert len(registry.all()) == 2
    assert calls == [1]  # the factory ran exactly once


def test_default_registry_returns_fifteen_builtin_plugins() -> None:
    registry = build_default_registry()
    plugins = registry.all()
    assert len(plugins) == 15
    kinds = {plugin.metadata.kind for plugin in plugins}
    assert kinds == {"support", "reference"}
    assert len(builtin_plugin_factory()) == 15


@pytest.mark.asyncio
async def test_request_sink_is_passed_to_the_plugin() -> None:
    registry = FlowRegistry()
    plugin = _Plugin(_FLOW_ID)
    registry.register(plugin)
    sink = _RecordingSink()
    request = FlowRunRequest(case_id=_FLOW_ID, max_turns=2, sink=sink)
    await registry.get(_FLOW_ID).run(request)
    assert plugin.requests[0].sink is sink
    assert plugin.requests[0].max_turns == 2


def test_support_projection_is_exact_and_unknown_tools_hide_details() -> None:
    projected = SUPPORT_PROJECTOR.project(
        "phase2-01-bad-prompt-policy-answer",
        "get_order_status",
        {"order_id": "abc-123", "reason": "secret customer text"},
    )
    assert projected.safe is True
    assert "abc-123" in projected.label
    assert "secret customer text" not in projected.label

    hidden = SUPPORT_PROJECTOR.project(
        "phase2-01-bad-prompt-policy-answer",
        "invented_tool",
        {"order_id": "abc-123"},
    )
    assert hidden.safe is False
    assert hidden.label == "invented_tool (details hidden)"


def test_result_projection_shows_only_safe_fields_and_hides_the_rest() -> None:
    # Exact result fields are extracted as field=value tokens only.
    summary = REFERENCE_PROJECTOR.project_result(
        "flight_booking", "hold_booking", "HELD pnr=PNRABC123 fare=149.50 secret=supersecret"
    )
    assert "pnr=PNRABC123" in summary
    assert "fare=149.50" in summary
    assert "supersecret" not in summary
    assert "HELD" not in summary

    # Unknown or unprojected results never include raw text.
    hidden = REFERENCE_PROJECTOR.project_result(
        "flight_booking", "search_flights", "CT-102 2026-08-14T18:30:00Z seats=12"
    )
    assert hidden == "(result details hidden)"
    assert "CT-102" not in hidden

    unknown = REFERENCE_PROJECTOR.project_result(
        "unknown-flow", "some_tool", "RAW SECRET VALUE"
    )
    assert unknown == "(result details hidden)"


def test_reference_projection_covers_every_registered_workflow_tool() -> None:
    # Every built-in reference tool has an exact projection (no fallback).
    for persona in builtin_plugin_factory():
        if persona.metadata.kind != "reference":
            continue
        flow_id = persona.metadata.case_id
        assert flow_id.startswith("reference-")
        # The projection registry is keyed by workflow id; at least the known
        # tool names must project without falling back to details-hidden.
        for tool in ("get_order", "process_refund", "search_flights"):
            if flow_id == "reference-returns_resolution" and tool in {
                "get_order",
                "process_refund",
            }:
                projected = REFERENCE_PROJECTOR.project(
                    "returns_resolution", tool, {"order_id": "o-1"}
                )
                assert projected.safe is True


def test_tool_projector_protocol_is_structural() -> None:
    assert isinstance(SUPPORT_PROJECTOR, ToolProjector)
    assert isinstance(REFERENCE_PROJECTOR, ToolProjector)
