"""Full-screen Textual viewer for one generic user-simulator flow.

The application is an optional interactive renderer. It consumes the same
``FlowPlugin`` and ``SimulationEvent`` contracts as Rich, and it never owns
business execution, persistence, preflight, or configuration.
"""

from __future__ import annotations

from dataclasses import replace
from time import monotonic
from typing import ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.message import Message
from textual.widgets import Button, DataTable, Footer, Input, Label, Static

from app.domain.user_simulator.events import EventKind, SimulationEvent
from app.domain.user_simulator.flows import (
    FlowMetadata,
    FlowPlugin,
    FlowRunRequest,
    FlowRunResult,
)


class EventReceived(Message):
    """One in-memory display event delivered to the Textual message loop."""

    def __init__(self, event: SimulationEvent) -> None:
        super().__init__()
        self.event = event


class TextualSimulatorApp(App[FlowRunResult | None]):
    """Keyboard-first live timeline and completed-run inspection workspace."""

    TITLE = "Agent Reliability Lab"
    SUB_TITLE = "User simulator"
    CSS = """
    Screen {
        background: #080b10;
        color: #dce4ee;
    }

    #topbar {
        height: 5;
        padding: 1 2;
        background: #0d131c;
        border-bottom: solid #1d2a3a;
    }

    #brand {
        width: 1fr;
        color: #78dce8;
        text-style: bold;
    }

    #status {
        width: auto;
        min-width: 14;
        padding: 0 2;
        background: #152334;
        color: #78dce8;
        text-align: center;
        text-style: bold;
    }

    #status.verified {
        background: #123629;
        color: #7bd88f;
    }

    #status.failed {
        background: #3a1920;
        color: #ff6188;
    }

    #status.review {
        background: #3a2e16;
        color: #f0c36a;
    }

    #scenario {
        height: 2;
        color: #f2f5f8;
        text-style: bold;
    }

    #workspace {
        height: 1fr;
        padding: 1;
    }

    .rail {
        width: 25;
        min-width: 20;
        padding: 1 2;
        background: #0d131c;
        border: solid #1d2a3a;
    }

    #details-rail {
        width: 31;
    }

    .rail-title {
        height: 2;
        color: #78dce8;
        text-style: bold;
    }

    .muted {
        color: #7f8da3;
    }

    .metric {
        height: 2;
        color: #dce4ee;
    }

    #timeline-pane {
        width: 1fr;
        margin: 0 1;
    }

    #filter {
        height: 3;
        margin-bottom: 1;
        border: tall #1d2a3a;
        background: #0d131c;
    }

    #filter:focus {
        border: tall #78dce8;
    }

    #timeline {
        height: 1fr;
        background: #0a0f16;
        border: solid #1d2a3a;
    }

    DataTable > .datatable--header {
        background: #111c28;
        color: #78dce8;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #17324a;
        color: #ffffff;
    }

    #detail {
        height: 1fr;
        color: #bac5d3;
    }

    #result {
        display: none;
        height: auto;
        margin-top: 1;
        padding: 1;
        background: #111c28;
        border-left: thick #78dce8;
    }

    #result.verified {
        border-left: thick #7bd88f;
    }

    #result.review {
        border-left: thick #f0c36a;
    }

    #result.failed {
        border-left: thick #ff6188;
    }

    #exit {
        display: none;
        width: 100%;
        margin-top: 1;
        background: #78dce8;
        color: #071016;
        text-style: bold;
    }

    #paused {
        display: none;
        dock: top;
        height: 1;
        background: #e6b450;
        color: #17120a;
        text-align: center;
        text-style: bold;
    }

    """

    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("ctrl+f", "focus_filter", "Filter", show=True, priority=True),
        Binding("space", "toggle_pause", "Pause view", show=True, priority=True),
        Binding("ctrl+l", "clear_filter", "Clear filter", show=True, priority=True),
        Binding("q", "finish", "Exit", show=True, priority=True),
    ]

    def __init__(
        self,
        plugin: FlowPlugin,
        request: FlowRunRequest,
        metadata: FlowMetadata,
        *,
        scenario_name: str,
        profile_label: str,
    ) -> None:
        super().__init__()
        self._plugin = plugin
        self._request = request
        self._metadata = metadata
        self._scenario_name = scenario_name
        self._profile_label = profile_label
        self._events: list[SimulationEvent] = []
        self._visible: list[SimulationEvent] = []
        self._pending: list[SimulationEvent] = []
        self._pending_sequences: set[tuple[str, int]] = set()
        self._result: FlowRunResult | None = None
        self._finished = False
        self._paused = False
        self._tool_calls = 0
        self._errors = 0
        self._turns = 0
        self._started_at = monotonic()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("VIEW PAUSED — the run continues", id="paused")
            with Vertical(id="topbar"):
                with Horizontal():
                    yield Static("AGENT RELIABILITY LAB  /  LIVE RUN", id="brand")
                    yield Label("● RUNNING", id="status")
                yield Static(self._scenario_name, id="scenario")
            with Horizontal(id="workspace"):
                with Vertical(classes="rail", id="context-rail"):
                    yield Static("RUN CONTEXT", classes="rail-title")
                    yield Static(self._metadata.kind.upper(), id="kind", classes="metric")
                    yield Static(self._metadata.case_id, id="case", classes="muted")
                    yield Static("\nRUN ID", classes="rail-title")
                    yield Static("pending", id="run-id", classes="muted")
                    yield Static("\nENVIRONMENT", classes="rail-title")
                    yield Static(self._profile_label, classes="muted")
                    yield Static("\nRUN AT A GLANCE", classes="rail-title")
                    yield Static("Events       0", id="metric-events", classes="metric")
                    yield Static("Turns        0", id="metric-turns", classes="metric")
                    yield Static("Tool calls   0", id="metric-tools", classes="metric")
                    yield Static("Errors       0", id="metric-errors", classes="metric")
                with Vertical(id="timeline-pane"):
                    yield Input(
                        placeholder="Find an event by type, source, or detail  [ctrl+f]",
                        id="filter",
                    )
                    yield DataTable(id="timeline", cursor_type="row", zebra_stripes=True)
                with Vertical(classes="rail", id="details-rail"):
                    yield Static("SELECTED EVENT", classes="rail-title")
                    yield Static(
                        "Select an event to see what happened.",
                        id="detail",
                        classes="muted",
                    )
                    yield Static("", id="result")
                    yield Button("Exit to terminal", id="exit", variant="primary")
            yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#timeline", DataTable)
        table.add_columns("#", "Event", "Source", "Detail")
        table.cursor_type = "row"
        table.focus()
        self.set_interval(1.0, self._update_elapsed)
        self.run_worker(self._run_flow(), exclusive=True, name="simulation")

    def on_resize(self, event: Resize) -> None:
        """Preserve the timeline at narrow widths by hiding secondary rails."""
        show_rails = event.size.width > 84
        self.query_one("#context-rail").display = show_rails
        self.query_one("#details-rail").display = show_rails
        self.query_one("#timeline-pane").styles.margin = (0, 1 if show_rails else 0)

    async def _run_flow(self) -> None:
        try:
            request = replace(self._request, sink=self)
            self._result = await self._plugin.run(request)
        except Exception as error:  # noqa: BLE001 - render a safe boundary error
            self._set_failed(type(error).__name__)
            return
        self._set_complete(self._result)

    def emit(self, event: SimulationEvent) -> None:
        """Implement ``EventSink`` without persisting display-only values."""
        self.post_message(EventReceived(event))

    @on(EventReceived)
    def receive_event(self, message: EventReceived) -> None:
        event = message.event
        if not self._events:
            self.query_one("#run-id", Static).update(event.persistent.run_id)
        self._events.append(event)
        display = event.display
        if display is not None:
            if display.kind is EventKind.USER:
                self._turns += 1
            elif display.kind is EventKind.TOOL_SELECTED:
                self._tool_calls += 1
            elif display.kind is EventKind.ERROR:
                self._errors += 1
        self._update_metrics()
        if self._paused:
            self._pending.append(event)
            self._pending_sequences.add(
                (event.persistent.run_id, event.persistent.seq)
            )
            return
        if self._matches(event, self.query_one("#filter", Input).value):
            self._append_row(event)

    def _append_row(self, event: SimulationEvent) -> None:
        display = event.display
        if display is None:
            return
        self._visible.append(event)
        detail = " ".join((display.text or "").split())
        table = self.query_one("#timeline", DataTable)
        table.add_row(
            str(display.seq),
            display.kind.value.replace("_", " "),
            display.source.value,
            detail,
            key=f"{event.persistent.run_id}:{display.seq}",
        )
        table.scroll_end(animate=False)

    @on(Input.Changed, "#filter")
    def filter_changed(self, message: Input.Changed) -> None:
        self._render_rows(message.value)

    def _render_rows(self, query: str) -> None:
        table = self.query_one("#timeline", DataTable)
        table.clear()
        self._visible.clear()
        for event in self._events:
            if self._paused and (
                event.persistent.run_id,
                event.persistent.seq,
            ) in self._pending_sequences:
                continue
            if self._matches(event, query):
                self._append_row(event)

    @staticmethod
    def _matches(event: SimulationEvent, query: str) -> bool:
        if not query.strip():
            return True
        display = event.display
        if display is None:
            return False
        haystack = " ".join(
            (display.kind.value, display.source.value, display.text, *display.detail)
        ).lower()
        return all(term in haystack for term in query.lower().split())

    @on(DataTable.RowHighlighted, "#timeline")
    def row_highlighted(self, message: DataTable.RowHighlighted) -> None:
        if message.cursor_row < 0 or message.cursor_row >= len(self._visible):
            return
        display = self._visible[message.cursor_row].display
        if display is None:
            return
        timestamp = display.timestamp.strftime("%H:%M:%S.%f")[:-3]
        text = display.text or "(no display detail)"
        detail = " · ".join(display.detail)
        if detail:
            text = f"{text}\n\n{detail}"
        self.query_one("#detail", Static).update(
            f"EVENT {display.seq:02d}  /  {display.kind.value.replace('_', ' ').upper()}\n"
            f"{display.source.value}  ·  {timestamp}\n\n"
            f"{text}\n\n"
            "Sensitive conversation text is not written to the run artifacts."
        )

    def _update_metrics(self) -> None:
        self.query_one("#metric-events", Static).update(f"Events       {len(self._events)}")
        self.query_one("#metric-turns", Static).update(f"Turns        {self._turns}")
        self.query_one("#metric-tools", Static).update(f"Tool calls   {self._tool_calls}")
        self.query_one("#metric-errors", Static).update(f"Errors       {self._errors}")

    def _set_complete(self, result: FlowRunResult) -> None:
        self._finished = True
        report = result.report
        verified = report.verified_goal
        status = self.query_one("#status", Label)
        status.update("✓ VERIFIED" if verified else "! CHECK RESULT")
        status.set_class(verified, "verified")
        summary = (
            f"{report.end_reason}\n"
            f"{report.turns} turns  ·  {report.total_tokens} tokens  ·  "
            f"{report.total_latency_ms:.0f} ms"
        )
        if report.cost_usd is not None:
            summary += f"  ·  ${report.cost_usd:.4f}"
        summary += (
            f"\n\nEvents  {result.transcript_path}\n"
            f"Report  {result.report_path}"
        )
        result_view = self.query_one("#result", Static)
        result_view.update(summary)
        result_view.remove_class("review", "failed")
        result_view.add_class("verified" if verified else "review")
        result_view.display = True
        status.remove_class("failed", "review")
        status.add_class("verified" if verified else "review")
        self.query_one("#exit", Button).display = True
        self.notify("Run complete. Review any event, then press q to exit.")

    def _set_failed(self, error_name: str) -> None:
        self._finished = True
        self._errors += 1
        self._update_metrics()
        status = self.query_one("#status", Label)
        status.update("× FAILED")
        status.remove_class("verified", "review")
        status.add_class("failed")
        result_view = self.query_one("#result", Static)
        result_view.update(
            f"The live view stopped before the run completed ({error_name}). "
            "Check the run log."
        )
        result_view.remove_class("verified", "review")
        result_view.add_class("failed")
        result_view.display = True
        self.query_one("#exit", Button).display = True

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_clear_filter(self) -> None:
        field = self.query_one("#filter", Input)
        field.value = ""
        self._render_rows("")
        self.query_one("#timeline", DataTable).focus()

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        self.query_one("#paused", Static).display = self._paused
        if not self._paused:
            self._pending.clear()
            self._pending_sequences.clear()
            self._render_rows(self.query_one("#filter", Input).value)

    def _update_elapsed(self) -> None:
        """Keep a small live clock in the status line without touching the run."""
        if self._finished:
            return
        elapsed = int(monotonic() - self._started_at)
        self.query_one("#status", Label).update(f"● RUNNING  {elapsed:02d}s")

    def action_finish(self) -> None:
        if not self._finished:
            self.notify(
                "The run is still active. Wait for verified cleanup before exit.",
                severity="warning",
            )
            return
        self.exit(self._result)

    @on(Button.Pressed, "#exit")
    def exit_button(self) -> None:
        self.action_finish()


async def run_textual_simulator(
    plugin: FlowPlugin,
    request: FlowRunRequest,
    *,
    scenario_name: str,
    profile_label: str,
) -> FlowRunResult:
    """Run one plugin inside the full-screen TUI and return its final result."""
    app = TextualSimulatorApp(
        plugin,
        request,
        plugin.metadata,
        scenario_name=scenario_name,
        profile_label=profile_label,
    )
    result = await app.run_async()
    if result is None:
        raise RuntimeError("Textual simulator closed without a completed result")
    return result
