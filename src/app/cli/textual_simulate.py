"""Full-screen Textual viewer for one generic user-simulator flow.

The application is an optional interactive renderer. It consumes the same
``FlowPlugin`` and ``SimulationEvent`` contracts as Rich, and it never owns
business execution, persistence, preflight, or configuration.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from pathlib import Path
from time import monotonic
from typing import Any, ClassVar, cast

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.message import Message
from textual.widgets import Button, DataTable, Input, Label, Static

from app.domain.user_simulator.events import (
    DisplayEvent,
    EventKind,
    SimulationEvent,
)
from app.domain.user_simulator.flows import (
    FlowMetadata,
    FlowPlugin,
    FlowRegistry,
    FlowRunRequest,
    FlowRunResult,
)
from app.domain.user_simulator.manifests import (
    CatalogError,
    EnvironmentProfile,
    Scenario,
    SimulationCatalog,
)
from app.domain.user_simulator.preflight import (
    EnvironmentProfileLike,
    resolve_runtime,
    run_preflight,
)


class EventCategory(str, Enum):
    """Event categories for fast keyboard-driven filtering."""

    ALL = "all"
    DIALOG = "dialog"
    TOOLS = "tools"
    ERRORS = "errors"
    STATE = "state"


class WorkspacePage(str, Enum):
    """Top-level pages in the simulator command center."""

    SETUP = "setup"
    OVERVIEW = "overview"
    TIMELINE = "timeline"
    EVIDENCE = "evidence"


class SetupStep(str, Enum):
    """Questions in the local simulation setup flow."""

    SCENARIO = "scenario"
    PERSONA = "persona"
    REQUEST = "request"
    GOAL = "goal"
    TURNS = "turns"
    PROFILE = "profile"
    REVIEW = "review"


_SETUP_STEPS = tuple(SetupStep)
_SETUP_QUESTIONS: dict[SetupStep, str] = {
    SetupStep.SCENARIO: "choose a simulation",
    SetupStep.PERSONA: "who is making the request?",
    SetupStep.REQUEST: "what do they say first?",
    SetupStep.GOAL: "what should happen?",
    SetupStep.TURNS: "how many turns can the run use?",
    SetupStep.PROFILE: "where should the run happen?",
    SetupStep.REVIEW: "ready to start?",
}
_SETUP_FOCUS_IDS: dict[SetupStep, str] = {
    SetupStep.SCENARIO: "#scenarios-table",
    SetupStep.PERSONA: "#input-persona",
    SetupStep.REQUEST: "#input-script",
    SetupStep.GOAL: "#input-goal",
    SetupStep.TURNS: "#input-turns",
    SetupStep.PROFILE: "#input-profile",
    SetupStep.REVIEW: "#btn-launch",
}


_CATEGORY_KINDS: dict[EventCategory, frozenset[EventKind]] = {
    EventCategory.ALL: frozenset(EventKind),
    EventCategory.DIALOG: frozenset({EventKind.USER, EventKind.AGENT, EventKind.MODEL}),
    EventCategory.TOOLS: frozenset({EventKind.TOOL_SELECTED, EventKind.TOOL_RESULT}),
    EventCategory.ERRORS: frozenset({EventKind.ERROR, EventKind.RETRY}),
    EventCategory.STATE: frozenset(
        {
            EventKind.START,
            EventKind.DONE,
            EventKind.STATE,
            EventKind.APPROVAL,
            EventKind.CLEANUP,
        }
    ),
}

_KIND_STYLES: dict[EventKind, tuple[str, str]] = {
    EventKind.START: ("start", "bold #d8d8d8"),
    EventKind.USER: ("user", "bold #f2f2f2"),
    EventKind.AGENT: ("agent", "bold #f2f2f2"),
    EventKind.MODEL: ("model", "bold #d8d8d8"),
    EventKind.TOOL_SELECTED: ("call", "bold #f2f2f2"),
    EventKind.TOOL_RESULT: ("result", "bold #d8d8d8"),
    EventKind.APPROVAL: ("approval", "bold #e5c558"),
    EventKind.RETRY: ("retry", "bold #e5c558"),
    EventKind.STATE: ("state", "bold #d8d8d8"),
    EventKind.DONE: ("done", "bold #f2f2f2"),
    EventKind.ERROR: ("failed", "bold #ef5b5b"),
    EventKind.CLEANUP: ("cleanup", "bold #8a8a8a"),
}


def _format_kind_cell(kind: EventKind) -> Text:
    """Render a restrained event label."""
    label, style = _KIND_STYLES.get(kind, (kind.value, "bold #d8d8d8"))
    return Text(label, style=style)


def _format_detail_cell(display: DisplayEvent) -> Text:
    """Render a clean preview line for the timeline detail column."""
    raw = " ".join((display.text or "").split())
    if not raw:
        detail = Text("(empty)", style="dim")
    elif display.kind is EventKind.TOOL_SELECTED and "(" in raw:
        tool_name, rest = raw.split("(", 1)
        detail = Text()
        detail.append(tool_name, style="bold #f2f2f2")
        detail.append("(", style="dim")
        detail.append(rest[:-1] if rest.endswith(")") else rest, style="#b8b8b8")
        if rest.endswith(")"):
            detail.append(")", style="dim")
    elif display.kind is EventKind.ERROR:
        detail = Text(raw, style="#ef5b5b")
    elif display.kind in {EventKind.USER, EventKind.AGENT}:
        detail = Text(raw, style="#f2f2f2")
    else:
        detail = Text(raw, style="#b8b8b8")

    preview = Text(display.source.value, style="#777777")
    preview.append("  ")
    preview.append_text(detail)
    return preview


def _format_turn_cell(event: SimulationEvent) -> Text:
    """Render the shared turn number for related model and transcript events."""
    turn = dict(event.persistent.fields).get("turn")
    if isinstance(turn, int):
        return Text(f"{turn:02d}", style="bold #e5c558")
    return Text("--", style="#555555")


class EventReceived(Message):
    """One in-memory display event delivered to the Textual message loop."""

    def __init__(self, event: SimulationEvent) -> None:
        super().__init__()
        self.event = event


class TextualSimulatorApp(App[FlowRunResult | None]):
    """Keyboard-first command center for one generic user-simulator flow."""

    TITLE = "Simulate"
    SUB_TITLE = "User simulator"
    CSS = """
    Screen {
        background: #000000;
        color: #d8d8d8;
        scrollbar-background: #000000;
        scrollbar-color: #444444;
        scrollbar-color-hover: #777777;
        scrollbar-color-active: #a0a0a0;
        scrollbar-corner-color: #000000;
    }

    #app-shell {
        height: 1fr;
    }

    #paused {
        display: none;
        dock: top;
        height: 1;
        background: #000000;
        color: #e5c558;
        text-align: center;
        text-style: bold;
        border-bottom: solid #e5c558;
    }

    #topbar {
        height: 3;
        padding: 1 2 0 2;
        background: #000000;
        border-bottom: solid #333333;
    }

    #brand {
        width: auto;
        height: 1;
        margin-right: 2;
        color: #f2f2f2;
        text-style: bold;
    }

    #scenario {
        width: 1fr;
        height: 1;
        color: #a0a0a0;
    }

    #status {
        width: auto;
        min-width: 12;
        height: 1;
        color: #b8b8b8;
        text-align: right;
    }

    #status.verified {
        color: #f2f2f2;
    }

    #status.failed {
        color: #ef5b5b;
        text-style: bold;
    }

    #status.review {
        color: #e5c558;
        text-style: bold;
    }

    #pipeline-chips {
        width: auto;
        height: 1;
        margin-right: 2;
        color: #777777;
    }

    #page-nav {
        height: 2;
        padding: 0 2;
        background: #000000;
        color: #8a8a8a;
        border-bottom: solid #333333;
    }

    #workspace,
    #config-workspace {
        height: 1fr;
    }

    .page {
        height: 1fr;
        padding: 1 2;
    }

    .panel {
        padding: 0 1;
        background: #000000;
        border: none;
    }

    .section-title {
        height: 1;
        margin-top: 1;
        color: #f2f2f2;
        text-style: bold;
    }

    .eyebrow {
        height: 1;
        color: #777777;
    }

    .muted {
        color: #8a8a8a;
    }

    .metric {
        height: 1;
        color: #d8d8d8;
    }

    .field-label {
        height: 1;
        margin-top: 1;
        color: #a0a0a0;
    }

    .config-input {
        height: 3;
        border: tall #444444;
        background: #000000;
        color: #f2f2f2;
    }

    .config-input:focus {
        border: tall #d8d8d8;
        background: #202020;
    }

    #config-workspace {
        align: center top;
        padding: 1 2;
    }

    #setup-sheet {
        width: 72;
        min-width: 36;
        height: 1fr;
        padding: 1 2 0 2;
    }

    #setup-progress {
        height: 1;
        color: #777777;
    }

    #setup-question {
        height: 2;
        margin-top: 1;
        color: #f2f2f2;
        text-style: bold;
    }

    .setup-step {
        height: 1fr;
        margin-top: 1;
    }

    #config-review-card {
        height: auto;
        margin-top: 1;
        padding: 1 0;
        color: #d8d8d8;
        background: #000000;
        border-top: solid #333333;
        border-bottom: solid #333333;
    }

    #setup-error {
        height: auto;
        max-height: 4;
        color: #e5c558;
    }

    #setup-actions {
        height: 3;
        align-horizontal: right;
    }

    #setup-actions Button {
        width: auto;
        min-width: 12;
        margin-left: 1;
        background: #202020;
        color: #d8d8d8;
        border: none;
    }

    #setup-actions Button:focus,
    #setup-actions Button:hover {
        background: #d8d8d8;
        color: #000000;
    }

    #btn-launch,
    #exit {
        background: #e8e8e8;
        color: #000000;
        text-style: bold;
    }

    #btn-launch:hover,
    #exit:hover {
        background: #ffffff;
    }

    #overview-page {
        padding-top: 2;
    }

    #overview-hero {
        height: 10;
    }

    #overview-focus {
        width: 2fr;
        margin-right: 1;
    }

    #overview-health {
        width: 1fr;
    }

    #overview-title {
        height: 2;
        margin-top: 1;
        color: #f2f2f2;
        text-style: bold;
    }

    #overview-activity {
        height: 3;
        margin-top: 1;
        padding: 0 1;
        color: #d8d8d8;
        background: #000000;
        border-left: solid #555555;
    }

    .metric-row {
        height: 4;
        margin-top: 1;
    }

    .metric-card {
        width: 1fr;
        height: 3;
        margin-right: 1;
        padding: 0 1;
        background: #000000;
        border-top: solid #333333;
    }

    .metric-card:last-child {
        margin-right: 0;
    }

    .metric-value {
        height: 1;
        color: #f2f2f2;
        text-style: bold;
    }

    #overview-grid {
        height: 1fr;
        margin-top: 1;
    }

    #overview-path-panel,
    #overview-events-panel {
        width: 1fr;
    }

    #overview-path-panel {
        margin-right: 1;
    }

    #overview-path,
    #overview-recent {
        height: 1fr;
        margin-top: 1;
        padding: 1;
        color: #d8d8d8;
        background: #000000;
        border-top: solid #333333;
    }

    #timeline-page {
        padding-top: 1;
    }

    #timeline-workspace {
        height: 1fr;
    }

    .rail {
        width: 24;
        min-width: 20;
        padding: 0 1;
        background: #000000;
        border: none;
        border-right: solid #333333;
    }

    #details-rail {
        width: 30;
        min-width: 26;
        border: none;
        border-left: solid #333333;
    }

    #timeline-pane {
        width: 1fr;
        margin: 0 1;
    }

    #timeline-heading {
        height: 1;
        color: #f2f2f2;
        text-style: bold;
    }

    #timeline-subtitle {
        height: 1;
        margin-bottom: 1;
        color: #8a8a8a;
    }

    #filter {
        height: 3;
        border: tall #444444;
        background: #000000;
        color: #f2f2f2;
    }

    #filter:focus {
        border: tall #d8d8d8;
        background: #202020;
    }

    #category-bar {
        height: 1;
        margin-top: 1;
        margin-bottom: 1;
        color: #8a8a8a;
    }

    #timeline,
    #scenarios-table {
        height: 1fr;
        background: #000000;
        border: none;
    }

    DataTable > .datatable--header {
        background: #000000;
        color: #a0a0a0;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #282828;
        color: #ffffff;
        text-style: bold;
    }

    DataTable > .datatable--odd-row {
        background: #000000;
    }

    DataTable > .datatable--even-row {
        background: #000000;
    }

    .rail-title {
        height: 1;
        margin-top: 1;
        color: #f2f2f2;
        text-style: bold;
    }

    #detail {
        height: 1fr;
        margin-top: 1;
        padding: 1;
        color: #d8d8d8;
        background: #000000;
        border: none;
    }

    #evidence-page {
        padding-top: 2;
    }

    #evidence-workspace {
        height: 1fr;
    }

    #evidence-main {
        width: 2fr;
        margin-right: 1;
    }

    #evidence-side {
        width: 1fr;
    }

    #result {
        display: none;
        height: auto;
        margin-top: 1;
        padding: 1;
        color: #d8d8d8;
        background: #000000;
        border-top: solid #333333;
        border-bottom: solid #333333;
    }

    #result.verified {
        color: #f2f2f2;
    }

    #result.review {
        color: #e5c558;
    }

    #result.failed {
        color: #ef5b5b;
    }

    #evidence-observed,
    #evidence-artifacts {
        height: 1fr;
        margin-top: 1;
        padding: 1;
        color: #d8d8d8;
        background: #000000;
        border-top: solid #333333;
    }

    #help-drawer {
        display: none;
        dock: top;
        width: 70;
        margin: 4 8;
        height: auto;
        background: #202020;
        border: solid #555555;
        padding: 1 2;
        color: #d8d8d8;
    }

    #shortcut-bar {
        dock: bottom;
        height: 2;
        padding: 0 2;
        background: #000000;
        color: #8a8a8a;
        border-top: solid #333333;
    }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("slash", "focus_filter", "find", show=False),
        Binding("ctrl+f", "focus_filter", "find", show=False),
        Binding("space", "toggle_pause", "pause", show=False),
        Binding("ctrl+l", "clear_filter", "clear", show=False),
        Binding("1", "set_category_all", "all", show=False),
        Binding("2", "set_category_dialog", "dialog", show=False),
        Binding("3", "set_category_tools", "tools", show=False),
        Binding("4", "set_category_errors", "errors", show=False),
        Binding("5", "set_category_state", "state", show=False),
        Binding("o", "go_overview", "overview", show=False),
        Binding("t", "go_timeline", "events", show=False),
        Binding("e", "go_evidence", "evidence", show=False),
        Binding("tab", "next_page", "next page", show=False),
        Binding("shift+tab", "previous_page", "previous page", show=False),
        Binding("question_mark", "toggle_help", "help", show=False),
        Binding("q", "finish", "exit", show=False),
    ]

    def __init__(
        self,
        plugin: FlowPlugin | None = None,
        request: FlowRunRequest | None = None,
        metadata: FlowMetadata | None = None,
        *,
        scenario_name: str = "",
        profile_label: str = "",
        catalog: SimulationCatalog | None = None,
        registry: FlowRegistry | None = None,
        db_probe: Any | None = None,
    ) -> None:
        super().__init__()
        self._plugin = plugin
        self._request = request
        self._metadata = metadata or (plugin.metadata if plugin else None)
        self._scenario_name = scenario_name
        self._profile_label = profile_label
        self._catalog = catalog
        self._flow_registry = registry
        self._db_probe = db_probe
        self._is_config_mode = plugin is None and catalog is not None
        self._scenarios: list[Scenario] = list(catalog.scenarios) if catalog else []
        self._selected_scenario: Scenario | None = self._scenarios[0] if self._scenarios else None
        self._events: list[SimulationEvent] = []
        self._visible: list[SimulationEvent] = []
        self._pending: list[SimulationEvent] = []
        self._pending_sequences: set[tuple[str, int]] = set()
        self._result: FlowRunResult | None = None
        self._finished = False
        self._paused = False
        self._active_category = EventCategory.ALL
        self._show_help = False
        self._active_page = WorkspacePage.SETUP if self._is_config_mode else WorkspacePage.TIMELINE
        self._setup_step = SetupStep.SCENARIO
        self._tool_calls = 0
        self._errors = 0
        self._turns = 0
        self._started_at = monotonic()

    def compose(self) -> ComposeResult:
        with Vertical(id="app-shell"):
            yield Static("view paused; the run continues", id="paused")
            with Horizontal(id="topbar"):
                yield Static("simulate", id="brand")
                yield Static(self._scenario_name or "new simulation", id="scenario")
                kind_text = self._metadata.kind if self._metadata else "setup"
                yield Static(kind_text, id="pipeline-chips")
                yield Label("running", id="status")
            yield Static(self._render_page_nav_text(), id="page-nav", markup=False)
            if self._is_config_mode:
                with Vertical(id="config-workspace", classes="page"):
                    with Vertical(id="setup-sheet"):
                        yield Static(self._render_setup_progress(), id="setup-progress")
                        yield Static("choose a simulation", id="setup-question")
                        with Vertical(id="setup-step-scenario", classes="setup-step"):
                            yield Static("select the local run you want to start.", classes="muted")
                            yield DataTable(
                                id="scenarios-table", cursor_type="row", zebra_stripes=False
                            )
                        with Vertical(id="setup-step-persona", classes="setup-step"):
                            yield Static("describe the person making the request.", classes="muted")
                            yield Input(
                                placeholder="customer persona",
                                id="input-persona",
                                classes="config-input",
                            )
                        with Vertical(id="setup-step-request", classes="setup-step"):
                            yield Static(
                                "enter the first message sent to the agent.", classes="muted"
                            )
                            yield Input(
                                placeholder="opening request",
                                id="input-script",
                                classes="config-input",
                            )
                        with Vertical(id="setup-step-goal", classes="setup-step"):
                            yield Static(
                                "state the result this run should produce.", classes="muted"
                            )
                            yield Input(
                                placeholder="expected result",
                                id="input-goal",
                                classes="config-input",
                            )
                        with Vertical(id="setup-step-turns", classes="setup-step"):
                            yield Static("use a number from 1 to 50.", classes="muted")
                            yield Input(
                                placeholder="8",
                                id="input-turns",
                                classes="config-input",
                                max_length=2,
                            )
                        with Vertical(id="setup-step-profile", classes="setup-step"):
                            yield Static(
                                "choose the environment used for this run.", classes="muted"
                            )
                            yield Input(
                                placeholder="lab-test-pg",
                                id="input-profile",
                                classes="config-input",
                            )
                        with Vertical(id="setup-step-review", classes="setup-step"):
                            yield Static("check the run before it starts.", classes="muted")
                            yield Static("", id="config-review-card")
                        yield Static("", id="setup-error")
                        with Horizontal(id="setup-actions"):
                            yield Button("back", id="btn-back")
                            yield Button("continue", id="btn-next")
                            yield Button("start simulation", id="btn-launch", variant="primary")
            with Vertical(id="workspace"):
                with Vertical(id="overview-page", classes="page"):
                    with Horizontal(id="overview-hero"):
                        with Vertical(classes="panel", id="overview-focus"):
                            yield Static("current run", classes="section-title")
                            yield Static(
                                self._scenario_name or "waiting for a simulation",
                                id="overview-title",
                            )
                            yield Static(
                                "follow the run from request to saved evidence.",
                                id="overview-description",
                                classes="muted",
                            )
                            yield Static("waiting for the first event...", id="overview-activity")
                        with Vertical(classes="panel", id="overview-health"):
                            yield Static("run totals", classes="section-title")
                            with Horizontal(classes="metric-row"):
                                with Vertical(classes="metric-card"):
                                    yield Static("events", classes="eyebrow")
                                    yield Static("0", id="overview-events", classes="metric-value")
                                with Vertical(classes="metric-card"):
                                    yield Static("turns", classes="eyebrow")
                                    yield Static("0", id="overview-turns", classes="metric-value")
                            with Horizontal(classes="metric-row"):
                                with Vertical(classes="metric-card"):
                                    yield Static("tools", classes="eyebrow")
                                    yield Static("0", id="overview-tools", classes="metric-value")
                                with Vertical(classes="metric-card"):
                                    yield Static("errors", classes="eyebrow")
                                    yield Static("0", id="overview-errors", classes="metric-value")
                    with Horizontal(id="overview-grid"):
                        with Vertical(classes="panel", id="overview-path-panel"):
                            yield Static("run path", classes="section-title")
                            yield Static(
                                "1  queued\n2  executing\n3  verifying\n4  evidence ready",
                                id="overview-path",
                                markup=False,
                            )
                        with Vertical(classes="panel", id="overview-events-panel"):
                            yield Static("latest events", classes="section-title")
                            yield Static(
                                "no events yet.",
                                id="overview-recent",
                                markup=False,
                            )
                with Vertical(id="timeline-page", classes="page"):
                    yield Static("event stream", id="timeline-heading")
                    yield Static(
                        "select an event to read its safe details.",
                        id="timeline-subtitle",
                    )
                    with Horizontal(id="timeline-workspace"):
                        with Vertical(classes="rail", id="context-rail"):
                            yield Static("run context", classes="rail-title")
                            kind_val = self._metadata.kind if self._metadata else "pending"
                            case_val = self._metadata.case_id if self._metadata else "pending"
                            yield Static(kind_val, id="kind", classes="metric")
                            yield Static(case_val, id="case", classes="muted")
                            yield Static("run id", classes="rail-title")
                            yield Static("pending", id="run-id", classes="muted")
                            yield Static("environment", classes="rail-title")
                            yield Static(
                                self._profile_label or "default",
                                id="profile",
                                classes="muted",
                            )
                            yield Static("totals", classes="rail-title")
                            yield Static("events       0", id="metric-events", classes="metric")
                            yield Static("turns        0", id="metric-turns", classes="metric")
                            yield Static("tool calls   0", id="metric-tools", classes="metric")
                            yield Static("errors       0", id="metric-errors", classes="metric")
                        with Vertical(id="timeline-pane"):
                            yield Input(
                                placeholder="find an event",
                                id="filter",
                            )
                            yield Static(
                                self._render_category_bar_text(),
                                id="category-bar",
                                markup=False,
                            )
                            yield DataTable(id="timeline", cursor_type="row", zebra_stripes=False)
                        with Vertical(classes="rail", id="details-rail"):
                            yield Static("selected event", classes="rail-title")
                            yield Static(
                                "select an event to see what happened.",
                                id="detail",
                                classes="muted",
                            )
                with Vertical(id="evidence-page", classes="page"):
                    with Horizontal(id="evidence-workspace"):
                        with Vertical(classes="panel", id="evidence-main"):
                            yield Static("evidence", classes="section-title")
                            yield Static(
                                "review what happened before leaving the workspace.",
                                classes="muted",
                            )
                            yield Static("", id="result")
                            yield Static("observed result", classes="section-title")
                            yield Static(
                                "the run has not completed yet.",
                                id="evidence-observed",
                                markup=False,
                            )
                        with Vertical(classes="panel", id="evidence-side"):
                            yield Static("files", classes="section-title")
                            yield Static(
                                "the run creates these files.",
                                id="evidence-artifacts",
                                markup=False,
                            )
                            yield Button("exit to terminal", id="exit", variant="primary")
            yield Static(self._help_text(), id="help-drawer", markup=False)
            yield Static(self._render_shortcuts(), id="shortcut-bar", markup=False)

    def on_mount(self) -> None:
        if self._is_config_mode:
            self.query_one("#workspace").display = False
            self.query_one("#status", Label).update("setup")
            sc_table = self.query_one("#scenarios-table", DataTable)
            sc_table.add_columns("simulation", "group")
            for sc in self._scenarios:
                sc_table.add_row(sc.scenario_id, sc.group, key=sc.scenario_id)
            if self._scenarios:
                self._load_scenario_defaults(self._scenarios[0])
            self._set_setup_step(SetupStep.SCENARIO)
            return

        self._set_page(WorkspacePage.TIMELINE)
        self._mount_live_timeline()

    def _mount_live_timeline(self) -> None:
        table = self.query_one("#timeline", DataTable)
        table.add_column("turn", width=4)
        table.add_column("event", width=8)
        table.add_column("detail", width=30)
        table.add_column("time", width=8)
        table.show_header = False
        table.cursor_type = "row"
        table.focus()
        self.set_interval(1.0, self._update_elapsed)
        self.run_worker(self._run_flow(), exclusive=True, name="simulation")

    def _load_scenario_defaults(self, sc: Scenario) -> None:
        self._selected_scenario = sc
        self.query_one("#scenario", Static).update(sc.name or sc.scenario_id)
        self.query_one("#pipeline-chips", Static).update(sc.group)
        self.query_one("#input-persona", Input).value = sc.persona
        self.query_one("#input-script", Input).value = sc.script
        self.query_one("#input-goal", Input).value = sc.goal
        self.query_one("#input-turns", Input).value = str(sc.max_turns)
        self.query_one("#input-profile", Input).value = sc.environment_profile
        self._update_setup_review()

    def _render_setup_progress(self) -> str:
        """Render one quiet progress line without repeating it as text."""
        current = _SETUP_STEPS.index(self._setup_step) + 1
        return "━" * current + "─" * (len(_SETUP_STEPS) - current)

    def _set_setup_step(self, step: SetupStep) -> None:
        self._setup_step = step
        for candidate in _SETUP_STEPS:
            self.query_one(f"#setup-step-{candidate.value}").display = candidate is step
        self.query_one("#setup-progress", Static).update(self._render_setup_progress())
        self.query_one("#setup-question", Static).update(_SETUP_QUESTIONS[step])
        self.query_one("#setup-error", Static).update("")
        self.query_one("#btn-back", Button).display = step is not SetupStep.SCENARIO
        self.query_one("#btn-next", Button).display = step is not SetupStep.REVIEW
        self.query_one("#btn-launch", Button).display = step is SetupStep.REVIEW
        if step is SetupStep.REVIEW:
            self._update_setup_review()
        self.query_one(_SETUP_FOCUS_IDS[step]).focus()
        self.query_one("#page-nav", Static).update(self._render_page_nav_text())
        self.query_one("#shortcut-bar", Static).update(self._render_shortcuts())

    def _update_setup_review(self) -> None:
        if not self._selected_scenario:
            return
        sc = self._selected_scenario
        review = (
            f"simulation    {sc.name or sc.scenario_id}\n"
            f"persona       {self.query_one('#input-persona', Input).value or 'not set'}\n"
            f"request       {self.query_one('#input-script', Input).value or 'not set'}\n"
            f"expected      {self.query_one('#input-goal', Input).value or 'not set'}\n"
            f"turn limit    {self.query_one('#input-turns', Input).value}\n"
            f"environment   {self.query_one('#input-profile', Input).value}"
        )
        self.query_one("#config-review-card", Static).update(review)

    def _validate_setup_step(self) -> bool:
        error = ""
        if self._setup_step is SetupStep.TURNS:
            raw = self.query_one("#input-turns", Input).value
            try:
                valid_turns = 1 <= int(raw) <= 50
            except ValueError:
                valid_turns = False
            if not valid_turns:
                error = "enter a number from 1 to 50."
        elif self._setup_step is SetupStep.PROFILE:
            profile_id = self.query_one("#input-profile", Input).value
            try:
                if not self._catalog:
                    raise LookupError
                self._catalog.environment(profile_id)
            except (CatalogError, LookupError):
                error = "choose an environment from this project."
        self.query_one("#setup-error", Static).update(error)
        return not error

    @on(DataTable.RowHighlighted, "#scenarios-table")
    def on_scenario_selected(self, message: DataTable.RowHighlighted) -> None:
        if message.cursor_row < 0 or message.cursor_row >= len(self._scenarios):
            return
        sc = self._scenarios[message.cursor_row]
        self._load_scenario_defaults(sc)

    @on(DataTable.RowSelected, "#scenarios-table")
    def on_scenario_confirmed(self) -> None:
        self.on_setup_next()

    @on(Button.Pressed, "#btn-next")
    def on_setup_next(self) -> None:
        if not self._validate_setup_step():
            return
        current = _SETUP_STEPS.index(self._setup_step)
        self._set_setup_step(_SETUP_STEPS[current + 1])

    @on(Button.Pressed, "#btn-back")
    def on_setup_back(self) -> None:
        current = _SETUP_STEPS.index(self._setup_step)
        if current:
            self._set_setup_step(_SETUP_STEPS[current - 1])

    @on(Button.Pressed, "#btn-launch")
    async def on_launch_clicked(self) -> None:
        if not self._selected_scenario or not self._flow_registry:
            return
        sc = self._selected_scenario
        plugin = self._flow_registry.get(sc.plugin_id)
        self._plugin = plugin
        self._metadata = plugin.metadata
        self._scenario_name = sc.name or sc.scenario_id

        turns_raw = self.query_one("#input-turns", Input).value
        try:
            turns = int(turns_raw)
            if not 1 <= turns <= 50:
                raise ValueError
        except ValueError:
            self._set_setup_step(SetupStep.TURNS)
            self.query_one("#setup-error", Static).update("enter a number from 1 to 50.")
            return

        profile_id = self.query_one("#input-profile", Input).value or sc.environment_profile
        try:
            if not self._catalog:
                raise LookupError
            profile: EnvironmentProfile = self._catalog.environment(profile_id)
        except (CatalogError, LookupError):
            self._set_setup_step(SetupStep.PROFILE)
            self.query_one("#setup-error", Static).update(
                "choose an environment from this project."
            )
            return
        root_path = Path(profile.artifact_root)
        self._profile_label = profile.label

        from app.cli.simulate import _env_for_preflight

        launch = self.query_one("#btn-launch", Button)
        launch.disabled = True
        self.query_one("#status", Label).update("checking")
        env = _env_for_preflight()
        issues = await run_preflight(
            plugin_id=sc.plugin_id,
            registry=self._flow_registry,
            profile=cast("EnvironmentProfileLike", profile),
            env=env,
            db_probe=self._db_probe,
        )
        runtime, runtime_issues = resolve_runtime(cast("EnvironmentProfileLike", profile), env)
        all_issues = (*issues, *runtime_issues)
        if all_issues:
            first = all_issues[0]
            self.query_one("#setup-error", Static).update(f"{first.message}\n{first.fix}")
            self.query_one("#status", Label).update("setup")
            launch.disabled = False
            return

        self._request = FlowRunRequest(
            case_id=sc.plugin_id,
            max_turns=turns,
            root=root_path,
            persona_context=self.query_one("#input-persona", Input).value or None,
            script=self.query_one("#input-script", Input).value or None,
            goal=self.query_one("#input-goal", Input).value or None,
            runtime=runtime,
        )

        self.query_one("#kind", Static).update(self._metadata.kind)
        self.query_one("#case", Static).update(self._metadata.case_id)
        self.query_one("#profile", Static).update(self._profile_label)
        self.query_one("#overview-title", Static).update(self._scenario_name)
        self.query_one("#overview-description", Static).update(
            "follow the run from request to saved evidence."
        )
        self.query_one("#config-workspace").display = False
        self.query_one("#workspace").display = True
        self.query_one("#status", Label).update("running")
        self._is_config_mode = False
        self._started_at = monotonic()
        self._set_page(WorkspacePage.TIMELINE)
        self._apply_live_layout(self.size.width)
        self._mount_live_timeline()

    def on_resize(self, event: Resize) -> None:
        """Preserve the primary task at narrow widths."""
        if not self._is_config_mode:
            self._apply_live_layout(event.size.width)

    def _apply_live_layout(self, width: int) -> None:
        show_rails = width > 84
        compact = not show_rails
        self.query_one("#context-rail").display = show_rails
        self.query_one("#details-rail").display = show_rails
        self.query_one("#timeline-pane").styles.margin = (0, 1 if show_rails else 0)
        overview_hero = self.query_one("#overview-hero")
        overview_hero.styles.layout = "vertical" if compact else "horizontal"
        overview_hero.styles.height = "auto" if compact else 10
        self.query_one("#overview-focus").styles.width = "1fr" if compact else "2fr"
        self.query_one("#overview-health").styles.width = "1fr"
        self.query_one("#overview-focus").styles.margin = (0, 0 if compact else 1)
        self.query_one("#overview-health").styles.margin = (1, 0) if compact else (0, 0)
        overview_grid = self.query_one("#overview-grid")
        overview_grid.styles.layout = "vertical" if compact else "horizontal"
        self.query_one("#overview-path-panel").styles.margin = (0, 0 if compact else 1)
        self.query_one("#overview-events-panel").styles.margin = (1, 0) if compact else (0, 0)
        evidence_workspace = self.query_one("#evidence-workspace")
        evidence_workspace.styles.layout = "vertical" if compact else "horizontal"
        self.query_one("#evidence-main").styles.width = "1fr" if compact else "2fr"
        self.query_one("#evidence-side").styles.width = "1fr"
        self.query_one("#evidence-main").styles.margin = (0, 0 if compact else 1)
        self.query_one("#evidence-side").styles.margin = (1, 0) if compact else (0, 0)

    def _render_page_nav_text(self) -> Text:
        """Render the stable page map shown below the run header."""
        if self._active_page is WorkspacePage.SETUP:
            return Text(f"setup / {_SETUP_QUESTIONS[self._setup_step]}", style="#8a8a8a")
        labels = (
            (WorkspacePage.OVERVIEW, "overview"),
            (WorkspacePage.TIMELINE, "events"),
            (WorkspacePage.EVIDENCE, "evidence"),
        )
        text = Text()
        for index, (page, name) in enumerate(labels):
            if index:
                text.append("    ")
            style = "underline bold #f2f2f2" if page is self._active_page else "#777777"
            text.append(name, style=style)
        return text

    def _render_shortcuts(self) -> str:
        if self._is_config_mode:
            return "tab move   enter choose   q exit"
        if self._active_page is WorkspacePage.TIMELINE:
            return "/ find   space pause   ? help   q exit"
        return "o overview   t events   e evidence   q exit"

    def _set_page(self, page: WorkspacePage) -> None:
        """Switch visible pages without changing the execution or event stream."""
        if page is WorkspacePage.SETUP:
            if not self._is_config_mode:
                return
            self._active_page = page
            self.query_one("#config-workspace").display = True
            self.query_one("#workspace").display = False
        else:
            if self._is_config_mode:
                return
            self._active_page = page
            self.query_one("#workspace").display = True
            for candidate in (
                WorkspacePage.OVERVIEW,
                WorkspacePage.TIMELINE,
                WorkspacePage.EVIDENCE,
            ):
                self.query_one(f"#{candidate.value}-page").display = candidate is page
            if page is WorkspacePage.TIMELINE:
                self.query_one("#timeline", DataTable).focus()
        self.query_one("#page-nav", Static).update(self._render_page_nav_text())
        self.query_one("#shortcut-bar", Static).update(self._render_shortcuts())

    def action_go_overview(self) -> None:
        self._set_page(WorkspacePage.OVERVIEW)

    def action_go_timeline(self) -> None:
        self._set_page(WorkspacePage.TIMELINE)

    def action_go_evidence(self) -> None:
        self._set_page(WorkspacePage.EVIDENCE)

    def action_next_page(self) -> None:
        if self._is_config_mode:
            return
        pages = [
            WorkspacePage.OVERVIEW,
            WorkspacePage.TIMELINE,
            WorkspacePage.EVIDENCE,
        ]
        next_index = (pages.index(self._active_page) + 1) % len(pages)
        self._set_page(pages[next_index])

    def action_previous_page(self) -> None:
        if self._is_config_mode:
            return
        pages = [
            WorkspacePage.OVERVIEW,
            WorkspacePage.TIMELINE,
            WorkspacePage.EVIDENCE,
        ]
        previous_index = (pages.index(self._active_page) - 1) % len(pages)
        self._set_page(pages[previous_index])

    async def _run_flow(self) -> None:
        if not self._plugin or not self._request:
            return
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
            self._update_overview(display)
        self._update_metrics()
        if self._paused:
            self._pending.append(event)
            self._pending_sequences.add((event.persistent.run_id, event.persistent.seq))
            return
        if self._matches(event, self.query_one("#filter", Input).value):
            self._append_row(event)

    def _append_row(self, event: SimulationEvent) -> None:
        display = event.display
        if display is None:
            return
        self._visible.append(event)
        table = self.query_one("#timeline", DataTable)
        table.add_row(
            _format_turn_cell(event),
            _format_kind_cell(display.kind),
            _format_detail_cell(display),
            display.timestamp.strftime("%H:%M:%S"),
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
            if (
                self._paused
                and (
                    event.persistent.run_id,
                    event.persistent.seq,
                )
                in self._pending_sequences
            ):
                continue
            if self._matches(event, query):
                self._append_row(event)

    def _matches(self, event: SimulationEvent, query: str) -> bool:
        display = event.display
        if display is None:
            return False
        allowed_kinds = _CATEGORY_KINDS.get(
            self._active_category, _CATEGORY_KINDS[EventCategory.ALL]
        )
        if display.kind not in allowed_kinds:
            return False
        if not query.strip():
            return True
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
        kind_name = display.kind.value.replace("_", " ")
        header = f"event {display.seq:02d} / {kind_name}\n{display.source.value}  ·  {timestamp}\n"

        text = display.text or "(no details)"
        detail = " · ".join(display.detail)
        body = text
        if detail:
            body = f"{body}\n\n{detail}"

        self.query_one("#detail", Static).update(
            f"{header}\n{body}\n\nprivate conversation text is not written to the run files."
        )

    def _update_metrics(self) -> None:
        self.query_one("#metric-events", Static).update(f"events       {len(self._events)}")
        self.query_one("#metric-turns", Static).update(f"turns        {self._turns}")
        self.query_one("#metric-tools", Static).update(f"tool calls   {self._tool_calls}")
        self.query_one("#metric-errors", Static).update(f"errors       {self._errors}")
        self.query_one("#overview-events", Static).update(str(len(self._events)))
        self.query_one("#overview-turns", Static).update(str(self._turns))
        self.query_one("#overview-tools", Static).update(str(self._tool_calls))
        self.query_one("#overview-errors", Static).update(str(self._errors))

    def _update_overview(self, display: DisplayEvent) -> None:
        """Keep the overview useful without turning it into a second timeline."""
        label, _ = _KIND_STYLES.get(display.kind, (display.kind.value.upper(), ""))
        detail = " ".join((display.text or "(empty)").split())
        self.query_one("#overview-activity", Static).update(
            f"{label}  /  {display.source.value}\n{detail}"
        )
        recent = self._events[-5:]
        recent_lines: list[str] = []
        for event in recent:
            event_display = event.display
            if event_display is None:
                continue
            event_label, _ = _KIND_STYLES.get(
                event_display.kind, (event_display.kind.value.upper(), "")
            )
            event_text = " ".join((event_display.text or "(empty)").split())
            recent_lines.append(f"{event_display.seq:02d}  {event_label:<5}  {event_text}")
        self.query_one("#overview-recent", Static).update(
            "\n".join(recent_lines) if recent_lines else "no events yet."
        )
        self.query_one("#overview-path", Static).update(self._render_run_path())

    def _render_run_path(self) -> str:
        """Show the run lifecycle as a short, readable sequence."""
        kinds = {event.display.kind for event in self._events if event.display is not None}
        stages = [
            ("request received", EventKind.START in kinds),
            ("agent working", bool(kinds & {EventKind.USER, EventKind.AGENT, EventKind.MODEL})),
            ("tools and state", bool(kinds & {EventKind.TOOL_SELECTED, EventKind.STATE})),
            ("verified evidence", self._finished and self._result is not None),
        ]
        lines: list[str] = []
        for index, (label, complete) in enumerate(stages, 1):
            marker = "✓" if complete else "·"
            lines.append(f"{marker}  {index}  {label}")
        return "\n".join(lines)

    def _set_complete(self, result: FlowRunResult) -> None:
        self._finished = True
        report = result.report
        verified = report.verified_goal
        status = self.query_one("#status", Label)
        status.update("verified" if verified else "check result")
        status.remove_class("failed", "review")
        status.add_class("verified" if verified else "review")
        summary = (
            f"{report.end_reason}\n"
            f"{report.turns} turns  ·  {report.total_tokens} tokens  ·  "
            f"{report.total_latency_ms:.0f} ms"
        )
        if report.cost_usd is not None:
            summary += f"  ·  ${report.cost_usd:.4f}"
        summary += f"\n\nevents  {result.transcript_path}\nreport  {result.report_path}"
        result_view = self.query_one("#result", Static)
        result_view.update(summary)
        result_view.remove_class("review", "failed")
        result_view.add_class("verified" if verified else "review")
        result_view.display = True
        self.query_one("#evidence-observed", Static).update(
            f"outcome      {'verified' if verified else 'needs review'}\n"
            f"end reason   {report.end_reason}\n"
            f"turns        {report.turns}\n"
            f"latency      {report.total_latency_ms:.0f} ms\n"
            f"tokens       {report.total_tokens}"
        )
        self.query_one("#evidence-artifacts", Static).update(
            f"events\n{result.transcript_path}\n\nreport\n{result.report_path}"
        )
        self.query_one("#overview-activity", Static).update(
            "verified / engine\nthe run is complete. evidence is ready."
            if verified
            else "check result / engine\nthe run is complete and needs review."
        )
        self.query_one("#overview-path", Static).update(self._render_run_path())
        self.query_one("#exit", Button).display = True
        self.notify("run complete. review an event or press q to exit.")

    def _set_failed(self, error_name: str) -> None:
        self._finished = True
        self._errors += 1
        self._update_metrics()
        status = self.query_one("#status", Label)
        status.update("failed")
        status.remove_class("verified", "review")
        status.add_class("failed")
        result_view = self.query_one("#result", Static)
        result_view.update(
            f"the run stopped before it completed ({error_name}). check the run log."
        )
        result_view.remove_class("verified", "review")
        result_view.add_class("failed")
        result_view.display = True
        self.query_one("#evidence-observed", Static).update(
            f"outcome      operational failure\n"
            f"error type   {error_name}\n"
            "the run stopped before it produced a result."
        )
        self.query_one("#evidence-artifacts", Static).update(
            "no complete result was produced.\ncheck the run log for the failure."
        )
        self.query_one("#overview-activity", Static).update(
            f"failed / engine\nthe run stopped before completion ({error_name})."
        )
        self.query_one("#overview-path", Static).update(self._render_run_path())
        self.query_one("#exit", Button).display = True

    def _render_category_bar_text(self) -> Text:
        cats = [
            ("1 all", EventCategory.ALL),
            ("2 dialog", EventCategory.DIALOG),
            ("3 tools", EventCategory.TOOLS),
            ("4 errors", EventCategory.ERRORS),
            ("5 state", EventCategory.STATE),
        ]
        text = Text()
        for index, (label, cat) in enumerate(cats):
            if index:
                text.append("  ")
            style = "underline #f2f2f2" if cat is self._active_category else "#777777"
            text.append(label, style=style)
        return text

    def _set_active_category(self, cat: EventCategory) -> None:
        if self._is_config_mode:
            return
        self._active_category = cat
        self.query_one("#category-bar", Static).update(self._render_category_bar_text())
        self._render_rows(self.query_one("#filter", Input).value)

    def action_set_category_all(self) -> None:
        self._set_active_category(EventCategory.ALL)

    def action_set_category_dialog(self) -> None:
        self._set_active_category(EventCategory.DIALOG)

    def action_set_category_tools(self) -> None:
        self._set_active_category(EventCategory.TOOLS)

    def action_set_category_errors(self) -> None:
        self._set_active_category(EventCategory.ERRORS)

    def action_set_category_state(self) -> None:
        self._set_active_category(EventCategory.STATE)

    def action_toggle_help(self) -> None:
        if self._is_config_mode:
            return
        self._show_help = not self._show_help
        self.query_one("#help-drawer", Static).display = self._show_help

    @staticmethod
    def _help_text() -> str:
        return (
            "keyboard\n"
            "  o overview   t events   e evidence   tab next page\n"
            "  / find       space pause           ctrl+l clear\n"
            "  1-5 filter events                  ? close help\n"
            "  q exit after cleanup"
        )

    def action_focus_filter(self) -> None:
        if self._is_config_mode:
            return
        self.query_one("#filter", Input).focus()

    def action_clear_filter(self) -> None:
        if self._is_config_mode:
            return
        field = self.query_one("#filter", Input)
        field.value = ""
        self._active_category = EventCategory.ALL
        self.query_one("#category-bar", Static).update(self._render_category_bar_text())
        self._render_rows("")
        self.query_one("#timeline", DataTable).focus()

    def action_toggle_pause(self) -> None:
        if self._is_config_mode:
            return
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
        self.query_one("#status", Label).update(f"running {elapsed:02d}s")

    def action_finish(self) -> None:
        if not self._finished and not self._is_config_mode:
            self.notify(
                "the run is still active. wait for cleanup before exit.",
                severity="warning",
            )
            return
        self.exit(self._result)

    @on(Button.Pressed, "#exit")
    def exit_button(self) -> None:
        self.action_finish()


async def run_interactive_workbench(
    catalog: SimulationCatalog,
    registry: FlowRegistry,
) -> FlowRunResult | None:
    """Run the interactive configuration and execution workbench."""
    app = TextualSimulatorApp(catalog=catalog, registry=registry)
    return await app.run_async()
