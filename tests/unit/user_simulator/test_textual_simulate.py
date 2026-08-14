"""Headless interaction tests for the optional full-screen simulator TUI."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Input, Label, Static

from app.cli.textual_simulate import TextualSimulatorApp
from app.domain.user_simulator.events import EventEmitter, EventKind, EventSource
from app.domain.user_simulator.flows import (
    FlowMetadata,
    FlowRegistry,
    FlowRunRequest,
    FlowRunResult,
)
from app.domain.user_simulator.manifests import (
    EnvironmentProfile,
    Scenario,
    SimulationCatalog,
)
from app.domain.user_simulator.models import SimulatorReport
from app.domain.user_simulator.preflight import PreflightIssue


class _TextualFlow:
    metadata = FlowMetadata(
        flow_id="textual-flow",
        case_id="textual-flow",
        kind="support",
        name="Textual flow",
    )

    def __init__(self) -> None:
        self.requests: list[FlowRunRequest] = []

    async def run(self, request: FlowRunRequest) -> FlowRunResult:
        assert request.sink is not None
        self.requests.append(request)
        emitter = EventEmitter("run-textual", request.case_id, [request.sink])
        emitter.emit(EventKind.START, EventSource.ENGINE, text="starting")
        emitter.emit(EventKind.USER, EventSource.PERSONA, text="Where is my order?", turn=1)
        emitter.emit(
            EventKind.TOOL_SELECTED,
            EventSource.SUPPORT,
            text="get_order_status(order_id=visible-safe-id)",
            tool="get_order_status",
        )
        emitter.emit(
            EventKind.TOOL_RESULT,
            EventSource.SUPPORT,
            text="get_order_status delivered",
            tool="get_order_status",
            outcome="ok",
        )
        emitter.emit(
            EventKind.DONE,
            EventSource.ENGINE,
            text="verified",
            verified=True,
        )
        return FlowRunResult(
            report=SimulatorReport(
                run_id="run-textual",
                case_id=request.case_id,
                kind="support",
                model_provider="fake",
                model_name="fake",
                end_reason="state_verified_success",
                turns=1,
                verified_goal=True,
                total_tokens=12,
                total_latency_ms=42,
            ),
            transcript_path=Path("artifacts/run-textual.jsonl"),
            report_path=Path("artifacts/run-textual.json"),
        )


def _app() -> TextualSimulatorApp:
    plugin = _TextualFlow()
    return TextualSimulatorApp(
        plugin,
        FlowRunRequest(case_id=plugin.metadata.case_id),
        plugin.metadata,
        scenario_name="Order status reliability",
        profile_label="Disposable local Postgres",
    )


@pytest.mark.asyncio
async def test_tui_runs_filters_inspects_and_returns_result() -> None:
    app = _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(0.2)

        table = app.query_one("#timeline", DataTable)
        assert table.row_count == 5
        assert str(app.query_one("#status", Label).render()) == "verified"
        assert str(app.query_one("#run-id", Static).render()) == "run-textual"
        assert app.query_one("#exit").display is True
        assert "artifacts/run-textual.json" in str(app.query_one("#result", Static).render())

        await pilot.press("ctrl+f")
        await pilot.press("t", "o", "o", "l")
        await pilot.pause()
        assert app.query_one("#filter", Input).value == "tool"
        assert table.row_count == 2

        await pilot.press("ctrl+l")
        await pilot.pause()
        assert table.row_count == 5

        await pilot.press("o")
        await pilot.pause()
        assert app.query_one("#overview-page").display is True
        assert app.query_one("#timeline-page").display is False
        assert "verified" in str(app.query_one("#overview-activity", Static).render())

        await pilot.press("e")
        await pilot.pause()
        assert app.query_one("#evidence-page").display is True
        assert "outcome" in str(app.query_one("#evidence-observed", Static).render())
        assert "artifacts/run-textual.json" in str(
            app.query_one("#evidence-artifacts", Static).render()
        )

        await pilot.press("t")
        await pilot.pause()
        assert app.query_one("#timeline-page").display is True

        table.move_cursor(row=1)
        await pilot.pause()
        detail = str(app.query_one("#detail", Static).render())
        assert "Where is my order?" in detail
        assert "not written to the run files" in detail

        table.move_cursor(row=0)
        await pilot.pause()
        assert "event 01" in str(app.query_one("#detail", Static).render())

        await pilot.press("q")

    assert app.return_value is not None
    assert app.return_value.report.verified_goal is True


@pytest.mark.asyncio
async def test_tui_pause_buffers_the_view_and_narrow_layout_hides_rails() -> None:
    app = _app()
    async with app.run_test(size=(72, 24)) as pilot:
        await pilot.pause(0.2)
        table = app.query_one("#timeline", DataTable)
        original_rows = table.row_count
        assert app.query_one("#context-rail").display is False
        assert app.query_one("#details-rail").display is False
        assert "engine" in str(table.get_row_at(0)[1])

        await pilot.press("space")
        emitter = EventEmitter("late", "textual-flow", [app])
        emitter.emit(EventKind.RETRY, EventSource.ENGINE, text="retry after timeout")
        await pilot.pause()
        assert table.row_count == original_rows
        assert app.query_one("#paused").display is True

        await pilot.press("space")
        await pilot.pause()
        assert table.row_count == original_rows + 1
        assert app.query_one("#paused").display is False

        await pilot.press("q")


@pytest.mark.asyncio
async def test_tui_category_filters_and_help_drawer() -> None:
    app = _app()
    async with app.run_test(size=(110, 32)) as pilot:
        await pilot.pause(0.2)
        table = app.query_one("#timeline", DataTable)
        assert table.row_count == 5

        # Filter to dialog events (USER turn)
        await pilot.press("2")
        await pilot.pause()
        assert table.row_count == 1
        assert "dialog" in str(app.query_one("#category-bar", Static).render())

        # Filter to tools events (TOOL_SELECTED, TOOL_RESULT)
        await pilot.press("3")
        await pilot.pause()
        assert table.row_count == 2
        assert "tools" in str(app.query_one("#category-bar", Static).render())

        # Reset to all
        await pilot.press("1")
        await pilot.pause()
        assert table.row_count == 5

        # Toggle help drawer
        help_drawer = app.query_one("#help-drawer", Static)
        assert help_drawer.display is False
        await pilot.press("question_mark")
        await pilot.pause()
        assert help_drawer.display is True
        assert "keyboard" in str(help_drawer.render())

        # Close help drawer
        await pilot.press("question_mark")
        await pilot.pause()
        assert help_drawer.display is False

        await pilot.press("q")


@pytest.mark.asyncio
async def test_interactive_workbench_configuration_and_launch(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    plugin = _TextualFlow()
    registry = FlowRegistry()
    registry.register(plugin)

    scenario = Scenario(
        scenario_id="order-test",
        plugin_id=plugin.metadata.flow_id,
        group="support",
        name="Order status test",
        description="Verify order status lookup",
        persona="Frustrated customer",
        script="Where is my package?",
        goal="Provide tracking number",
        max_turns=5,
        environment_profile="test-env",
    )
    profile = EnvironmentProfile(
        profile_id="test-env",
        label="Test Postgres",
        environment="test",
    )
    catalog = SimulationCatalog(
        scenarios=(scenario,),
        profiles=(profile,),
        issues=(),
    )

    app = TextualSimulatorApp(catalog=catalog, registry=registry)
    async with app.run_test(size=(72, 35)) as pilot:
        await pilot.pause(0.2)

        assert app.query_one("#config-workspace").display is True
        assert app.query_one("#workspace").display is False
        assert "setup" in str(app.query_one("#page-nav", Static).render())

        def visible_setup_steps() -> list[str | None]:
            return [step.id for step in app.query(".setup-step") if step.display]

        assert visible_setup_steps() == ["setup-step-scenario"]
        await pilot.press("enter")
        await pilot.pause()
        assert visible_setup_steps() == ["setup-step-persona"]

        persona_input = app.query_one("#input-persona", Input)
        persona_input.value = ""
        await pilot.press("q", "u", "i", "e", "t", "space", "q", "space", "u", "s", "e", "r")
        assert persona_input.value == "quiet q user"
        assert app.query_one("#config-workspace").display is True

        for expected_step in ("request", "goal", "turns"):
            app.query_one("#btn-next", Button).press()
            await pilot.pause()
            assert visible_setup_steps() == [f"setup-step-{expected_step}"]

        turns_input = app.query_one("#input-turns", Input)
        turns_input.value = "0"
        app.query_one("#btn-next", Button).press()
        await pilot.pause()
        assert visible_setup_steps() == ["setup-step-turns"]
        assert str(app.query_one("#setup-error", Static).render()) == (
            "enter a number from 1 to 50."
        )

        turns_input.value = "10"
        app.query_one("#btn-next", Button).press()
        await pilot.pause()
        assert visible_setup_steps() == ["setup-step-profile"]

        app.query_one("#btn-next", Button).press()
        await pilot.pause()
        assert visible_setup_steps() == ["setup-step-review"]
        assert "turn limit    10" in str(app.query_one("#config-review-card", Static).render())

        app.query_one("#btn-launch", Button).press()
        await pilot.pause(0.3)

        assert app.query_one("#config-workspace").display is False
        assert app.query_one("#workspace").display is True
        assert app.query_one("#timeline-page").display is True
        assert app.query_one("#context-rail").display is False
        assert app.query_one("#details-rail").display is False
        assert str(app.query_one("#status", Label).render()) == "verified"
        assert app.query_one("#timeline", DataTable).row_count == 5
        assert plugin.requests[0].runtime is not None
        assert plugin.requests[0].runtime.environment == "test"

        await pilot.press("q")

    assert app.return_value is not None
    assert app.return_value.report.verified_goal is True


@pytest.mark.asyncio
async def test_workbench_keeps_preflight_failure_in_setup(monkeypatch) -> None:
    plugin = _TextualFlow()
    registry = FlowRegistry()
    registry.register(plugin)
    scenario = Scenario(
        scenario_id="order-test",
        plugin_id=plugin.metadata.flow_id,
        group="support",
        name="Order status test",
        environment_profile="test-env",
    )
    profile = EnvironmentProfile(
        profile_id="test-env",
        label="Test Postgres",
        environment="test",
    )
    catalog = SimulationCatalog(scenarios=(scenario,), profiles=(profile,), issues=())

    async def _failed_preflight(**_kwargs) -> tuple[PreflightIssue, ...]:
        return (
            PreflightIssue(
                "database",
                "the test database is not available",
                "start the disposable database",
            ),
        )

    monkeypatch.setattr(
        "app.cli.textual_simulate.run_preflight",
        _failed_preflight,
    )

    app = TextualSimulatorApp(catalog=catalog, registry=registry)
    async with app.run_test(size=(90, 28)) as pilot:
        await pilot.pause()
        for _ in range(6):
            app.query_one("#btn-next", Button).press()
            await pilot.pause()
        app.query_one("#btn-launch", Button).press()
        await pilot.pause()

        assert app.query_one("#config-workspace").display is True
        assert app.query_one("#workspace").display is False
        assert "test database is not available" in str(
            app.query_one("#setup-error", Static).render()
        )
        assert plugin.requests == []
