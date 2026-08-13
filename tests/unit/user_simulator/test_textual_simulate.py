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


class _TextualFlow:
    metadata = FlowMetadata(
        flow_id="textual-flow",
        case_id="textual-flow",
        kind="support",
        name="Textual flow",
    )

    async def run(self, request: FlowRunRequest) -> FlowRunResult:
        assert request.sink is not None
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
        assert str(app.query_one("#status", Label).render()) == "VERIFIED"
        assert str(app.query_one("#run-id", Static).render()) == "run-textual"
        assert app.query_one("#exit").display is True
        assert "artifacts/run-textual.json" in str(
            app.query_one("#result", Static).render()
        )

        await pilot.press("ctrl+f")
        await pilot.press("t", "o", "o", "l")
        await pilot.pause()
        assert app.query_one("#filter", Input).value == "tool"
        assert table.row_count == 2

        await pilot.press("ctrl+l")
        await pilot.pause()
        assert table.row_count == 5

        table.move_cursor(row=1)
        await pilot.pause()
        detail = str(app.query_one("#detail", Static).render())
        assert "Where is my order?" in detail
        assert "not written to the run artifacts" in detail

        table.move_cursor(row=0)
        await pilot.pause()
        assert "EVENT 01" in str(app.query_one("#detail", Static).render())

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
        assert "DIALOG" in str(app.query_one("#category-bar", Static).render())

        # Filter to tools events (TOOL_SELECTED, TOOL_RESULT)
        await pilot.press("3")
        await pilot.pause()
        assert table.row_count == 2
        assert "TOOLS" in str(app.query_one("#category-bar", Static).render())

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
        assert "KEYBOARD SHORTCUTS" in str(help_drawer.render())

        # Close help drawer
        await pilot.press("question_mark")
        await pilot.pause()
        assert help_drawer.display is False

        await pilot.press("q")


@pytest.mark.asyncio
async def test_interactive_workbench_configuration_and_launch() -> None:
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
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause(0.2)

        # In configuration mode
        assert app.query_one("#config-workspace").display is True
        assert app.query_one("#workspace").display is False
        assert app.query_one("#input-persona", Input).value == "Frustrated customer"
        assert app.query_one("#input-turns", Input).value == "5"

        # Edit turn count
        turns_input = app.query_one("#input-turns", Input)
        turns_input.value = "10"
        await pilot.pause()
        assert turns_input.value == "10"

        # Click launch
        btn = app.query_one("#btn-launch", Button)
        btn.press()
        await pilot.pause(0.3)

        # Transitioned to live timeline
        assert app.query_one("#config-workspace").display is False
        assert app.query_one("#workspace").display is True
        assert str(app.query_one("#status", Label).render()) == "VERIFIED"
        assert app.query_one("#timeline", DataTable).row_count == 5

        await pilot.press("q")

    assert app.return_value is not None
    assert app.return_value.report.verified_goal is True


