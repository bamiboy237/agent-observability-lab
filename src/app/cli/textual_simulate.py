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
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.message import Message
from textual.widgets import Button, DataTable, Footer, Input, Label, Static

from app.domain.user_simulator.events import (
    DisplayEvent,
    EventKind,
    EventSource,
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
    EnvironmentProfile,
    Scenario,
    SimulationCatalog,
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
    EventKind.START: ("START", "bold #94a3b8"),
    EventKind.USER: ("USER", "bold #38bdf8"),
    EventKind.AGENT: ("AGENT", "bold #818cf8"),
    EventKind.MODEL: ("MODEL", "bold #c084fc"),
    EventKind.TOOL_SELECTED: ("CALL", "bold #22d3ee"),
    EventKind.TOOL_RESULT: ("RES", "bold #34d399"),
    EventKind.APPROVAL: ("AUTH", "bold #fbbf24"),
    EventKind.RETRY: ("RETRY", "bold #f59e0b"),
    EventKind.STATE: ("STATE", "bold #60a5fa"),
    EventKind.DONE: ("DONE", "bold #4ade80"),
    EventKind.ERROR: ("ERROR", "bold #f87171"),
    EventKind.CLEANUP: ("CLEAN", "bold #64748b"),
}

_SOURCE_STYLES: dict[EventSource, tuple[str, str]] = {
    EventSource.PERSONA: ("persona", "#38bdf8"),
    EventSource.SUPPORT: ("support", "#818cf8"),
    EventSource.REFERENCE: ("reference", "#c084fc"),
    EventSource.ENGINE: ("engine", "#64748b"),
    EventSource.CLI: ("cli", "#64748b"),
}


def _format_kind_cell(kind: EventKind) -> Text:
    """Render a colored badge for the event kind column."""
    label, style = _KIND_STYLES.get(kind, (kind.value.upper(), "bold #dce4ee"))
    return Text(label, style=style)


def _format_source_cell(source: EventSource) -> Text:
    """Render a styled label for the event source column."""
    label, style = _SOURCE_STYLES.get(source, (source.value, "dim"))
    return Text(label, style=style)


def _format_detail_cell(display: DisplayEvent) -> Text:
    """Render a clean preview line for the timeline detail column."""
    raw = " ".join((display.text or "").split())
    if not raw:
        return Text("(empty)", style="dim")
    if display.kind is EventKind.TOOL_SELECTED and "(" in raw:
        tool_name, rest = raw.split("(", 1)
        res = Text()
        res.append(tool_name, style="bold #22d3ee")
        res.append("(", style="dim")
        res.append(rest[:-1] if rest.endswith(")") else rest, style="#cbd5e1")
        if rest.endswith(")"):
            res.append(")", style="dim")
        return res
    if display.kind is EventKind.ERROR:
        return Text(raw, style="#fca5a5")
    if display.kind in {EventKind.USER, EventKind.AGENT}:
        return Text(raw, style="#f1f5f9")
    return Text(raw, style="#cbd5e1")


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
        background: #0b1016;
        color: #d9e5ee;
    }

    #app-shell {
        height: 1fr;
    }

    #paused {
        display: none;
        dock: top;
        height: 1;
        background: #d39a58;
        color: #0b1016;
        text-align: center;
        text-style: bold;
    }

    #topbar {
        height: 5;
        padding: 0 2;
        background: #111923;
        border-bottom: solid #263746;
    }

    #topbar-header {
        height: 3;
        margin-top: 1;
    }

    #brand-container {
        width: 1fr;
    }

    #brand {
        height: 1;
        color: #79f2d0;
        text-style: bold;
    }

    #brand-subtitle {
        height: 1;
        color: #7890a2;
    }

    #status {
        width: auto;
        min-width: 16;
        height: 2;
        padding: 0 2;
        background: #173042;
        color: #79f2d0;
        text-align: center;
        text-style: bold;
    }

    #status.verified {
        background: #123b32;
        color: #70e0b6;
    }

    #status.failed {
        background: #492522;
        color: #ff9f83;
    }

    #status.review {
        background: #41381a;
        color: #f0d477;
    }

    #scenario-bar {
        height: 1;
    }

    #scenario {
        width: 1fr;
        color: #f0f6f8;
        text-style: bold;
    }

    #pipeline-chips {
        width: auto;
        color: #8da5b5;
    }

    #page-nav {
        height: 2;
        padding: 0 2;
        background: #0f171f;
        color: #9db4c1;
        border-bottom: solid #1e2d39;
    }

    #workspace,
    #config-workspace {
        height: 1fr;
    }

    .page {
        height: 1fr;
        padding: 1 2 0 2;
    }

    .panel {
        padding: 0 1;
        background: #111923;
        border: solid #263746;
    }

    .section-title {
        height: 1;
        margin-top: 1;
        color: #79f2d0;
        text-style: bold;
    }

    .eyebrow {
        height: 1;
        color: #728999;
        text-style: bold;
    }

    .muted {
        color: #8198a7;
    }

    .metric {
        height: 1;
        color: #d9e5ee;
    }

    .field-label {
        height: 1;
        margin-top: 1;
        color: #90a6b3;
    }

    .config-input {
        height: 3;
        border: tall #263746;
        background: #0d141c;
        color: #f0f6f8;
    }

    .config-input:focus {
        border: tall #79f2d0;
        background: #16242d;
    }

    #config-workspace {
        padding: 1 2 0 2;
    }

    #scenarios-rail {
        width: 29;
        min-width: 22;
    }

    #config-form-pane {
        width: 1fr;
        margin: 0 1;
    }

    #config-review-pane {
        width: 35;
        min-width: 27;
    }

    #setup-copy {
        height: 2;
        margin-top: 1;
        color: #9aafba;
    }

    #config-review-card {
        height: 1fr;
        margin-top: 1;
        padding: 1;
        color: #c9d9e1;
        background: #0d141c;
        border: solid #263746;
    }

    #preflight-status {
        height: 2;
        margin-top: 1;
        padding: 0 1;
        background: #123b32;
        color: #70e0b6;
        text-style: bold;
    }

    #btn-launch,
    #exit {
        width: 100%;
        margin-top: 1;
        background: #79f2d0;
        color: #0b1016;
        text-style: bold;
    }

    #btn-launch:hover,
    #exit:hover {
        background: #a4ffe8;
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
        color: #f0f6f8;
        text-style: bold;
    }

    #overview-activity {
        height: 3;
        margin-top: 1;
        padding: 0 1;
        color: #d9e5ee;
        background: #0d141c;
        border-left: thick #79f2d0;
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
        background: #0d141c;
        border: solid #263746;
    }

    .metric-card:last-child {
        margin-right: 0;
    }

    .metric-value {
        height: 1;
        color: #f0f6f8;
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
        color: #c9d9e1;
        background: #0d141c;
        border: solid #263746;
    }

    #timeline-page {
        padding-top: 1;
    }

    #timeline-workspace {
        height: 1fr;
    }

    .rail {
        width: 27;
        min-width: 20;
        padding: 0 1;
        background: #111923;
        border: solid #263746;
    }

    #details-rail {
        width: 35;
        min-width: 26;
    }

    #timeline-pane {
        width: 1fr;
        margin: 0 1;
    }

    #timeline-heading {
        height: 1;
        color: #f0f6f8;
        text-style: bold;
    }

    #timeline-subtitle {
        height: 1;
        margin-bottom: 1;
        color: #8198a7;
    }

    #filter {
        height: 3;
        border: tall #263746;
        background: #0d141c;
        color: #f0f6f8;
    }

    #filter:focus {
        border: tall #79f2d0;
        background: #16242d;
    }

    #category-bar {
        height: 1;
        margin-top: 1;
        margin-bottom: 1;
        color: #90a6b3;
    }

    #timeline,
    #scenarios-table {
        height: 1fr;
        background: #0d141c;
        border: solid #263746;
    }

    DataTable > .datatable--header {
        background: #17252e;
        color: #79f2d0;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #1b3c43;
        color: #ffffff;
        text-style: bold;
    }

    DataTable > .datatable--odd-row {
        background: #101a22;
    }

    DataTable > .datatable--even-row {
        background: #0d141c;
    }

    .rail-title {
        height: 1;
        margin-top: 1;
        color: #79f2d0;
        text-style: bold;
    }

    #detail {
        height: 1fr;
        margin-top: 1;
        padding: 1;
        color: #c9d9e1;
        background: #0d141c;
        border: solid #263746;
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
        color: #d9e5ee;
        background: #0d141c;
        border: solid #263746;
        border-left: thick #79f2d0;
    }

    #result.verified {
        border-left: thick #70e0b6;
    }

    #result.review {
        border-left: thick #f0d477;
    }

    #result.failed {
        border-left: thick #ff9f83;
    }

    #evidence-observed,
    #evidence-artifacts {
        height: 1fr;
        margin-top: 1;
        padding: 1;
        color: #c9d9e1;
        background: #0d141c;
        border: solid #263746;
    }

    #help-drawer {
        display: none;
        dock: bottom;
        height: auto;
        background: #111923;
        border-top: solid #79f2d0;
        padding: 1 2;
        color: #d9e5ee;
    }

    Footer {
        background: #111923;
        color: #90a6b3;
        border-top: solid #263746;
    }
    """

    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("slash", "focus_filter", "Filter", show=True, priority=True),
        Binding("ctrl+f", "focus_filter", "Filter", show=False, priority=True),
        Binding("space", "toggle_pause", "Pause", show=True, priority=True),
        Binding("ctrl+l", "clear_filter", "Clear", show=True, priority=True),
        Binding("1", "set_category_all", "All", show=False, priority=True),
        Binding("2", "set_category_dialog", "Dialog", show=False, priority=True),
        Binding("3", "set_category_tools", "Tools", show=False, priority=True),
        Binding("4", "set_category_errors", "Errors", show=False, priority=True),
        Binding("5", "set_category_state", "State", show=False, priority=True),
        Binding("o", "go_overview", "Overview", show=True),
        Binding("t", "go_timeline", "Timeline", show=True),
        Binding("e", "go_evidence", "Evidence", show=True),
        Binding("tab", "next_page", "Next page", show=False),
        Binding("shift+tab", "previous_page", "Previous page", show=False),
        Binding("question_mark", "toggle_help", "Help", show=True, priority=True),
        Binding("q", "finish", "Exit", show=True, priority=True),
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
    ) -> None:
        super().__init__()
        self._plugin = plugin
        self._request = request
        self._metadata = metadata or (plugin.metadata if plugin else None)
        self._scenario_name = scenario_name
        self._profile_label = profile_label
        self._catalog = catalog
        self._flow_registry = registry
        self._is_config_mode = plugin is None and catalog is not None
        self._scenarios: list[Scenario] = list(catalog.scenarios) if catalog else []
        self._selected_scenario: Scenario | None = (
            self._scenarios[0] if self._scenarios else None
        )
        self._events: list[SimulationEvent] = []
        self._visible: list[SimulationEvent] = []
        self._pending: list[SimulationEvent] = []
        self._pending_sequences: set[tuple[str, int]] = set()
        self._result: FlowRunResult | None = None
        self._finished = False
        self._paused = False
        self._active_category = EventCategory.ALL
        self._show_help = False
        self._active_page = (
            WorkspacePage.SETUP if self._is_config_mode else WorkspacePage.TIMELINE
        )
        self._tool_calls = 0
        self._errors = 0
        self._turns = 0
        self._started_at = monotonic()

    def compose(self) -> ComposeResult:
        with Vertical(id="app-shell"):
            yield Static("VIEW PAUSED — the run continues", id="paused")
            with Vertical(id="topbar"):
                with Horizontal(id="topbar-header"):
                    with Vertical(id="brand-container"):
                        yield Static("SIMULATE", id="brand")
                        yield Static("USER SIMULATOR / COMMAND CENTER", id="brand-subtitle")
                    yield Label("RUNNING", id="status")
                with Horizontal(id="scenario-bar"):
                    yield Static(self._scenario_name or "Simulation Setup", id="scenario")
                    kind_text = f"[{self._metadata.kind.upper()}]" if self._metadata else "[SETUP]"
                    yield Static(kind_text, id="pipeline-chips")
            yield Static(self._render_page_nav_text(), id="page-nav", markup=False)
            if self._is_config_mode:
                with Horizontal(id="config-workspace", classes="page"):
                    with Vertical(classes="panel", id="scenarios-rail"):
                        yield Static("SIMULATIONS", classes="section-title")
                        yield Static("Choose a run recipe", classes="muted")
                        yield DataTable(
                            id="scenarios-table", cursor_type="row", zebra_stripes=True
                        )
                    with Vertical(classes="panel", id="config-form-pane"):
                        yield Static("RUN RECIPE", classes="section-title")
                        yield Static(
                            "Tune the caller, request, and success signal before launch.",
                            id="setup-copy",
                        )
                        yield Static("CALLER CONTEXT", classes="eyebrow")
                        yield Static(
                            "Persona",
                            classes="field-label",
                        )
                        yield Input(
                            placeholder="Customer persona",
                            id="input-persona",
                            classes="config-input",
                        )
                        yield Static(
                            "Opening request",
                            classes="field-label",
                        )
                        yield Input(
                            placeholder="Initial utterance",
                            id="input-script",
                            classes="config-input",
                        )
                        yield Static("SUCCESS SIGNAL", classes="eyebrow")
                        yield Static("Desired outcome", classes="field-label")
                        yield Input(
                            placeholder="Success criteria",
                            id="input-goal",
                            classes="config-input",
                        )
                        with Horizontal():
                            with Vertical():
                                yield Static("Max Turns (1-50)", classes="field-label")
                                yield Input(
                                    placeholder="8",
                                    id="input-turns",
                                    classes="config-input",
                                    max_length=2,
                                )
                            with Vertical():
                                yield Static("Environment Profile", classes="field-label")
                                yield Input(
                                    placeholder="lab-test-pg",
                            id="input-profile",
                            classes="config-input",
                        )
                        yield Button("Start Simulation", id="btn-launch", variant="primary")
                    with Vertical(classes="panel", id="config-review-pane"):
                        yield Static("PREFLIGHT", classes="section-title")
                        yield Static(
                            "Review the selected target and profile before launch. "
                            "The event stream stays append-only.",
                            classes="muted",
                        )
                        yield Static("", id="config-review-card")
                        yield Static("PROFILE SELECTED", id="preflight-status")
            with Vertical(id="workspace"):
                with Vertical(id="overview-page", classes="page"):
                    with Horizontal(id="overview-hero"):
                        with Vertical(classes="panel", id="overview-focus"):
                            yield Static("CURRENT RUN", classes="section-title")
                            yield Static(
                                self._scenario_name or "Waiting for a simulation",
                                id="overview-title",
                            )
                            yield Static(
                                "The live path will appear here as the run moves from "
                                "request to verified result.",
                                id="overview-description",
                                classes="muted",
                            )
                            yield Static("Waiting for the first event…", id="overview-activity")
                        with Vertical(classes="panel", id="overview-health"):
                            yield Static("RUN HEALTH", classes="section-title")
                            with Horizontal(classes="metric-row"):
                                with Vertical(classes="metric-card"):
                                    yield Static("EVENTS", classes="eyebrow")
                                    yield Static("0", id="overview-events", classes="metric-value")
                                with Vertical(classes="metric-card"):
                                    yield Static("TURNS", classes="eyebrow")
                                    yield Static("0", id="overview-turns", classes="metric-value")
                            with Horizontal(classes="metric-row"):
                                with Vertical(classes="metric-card"):
                                    yield Static("TOOLS", classes="eyebrow")
                                    yield Static("0", id="overview-tools", classes="metric-value")
                                with Vertical(classes="metric-card"):
                                    yield Static("ERRORS", classes="eyebrow")
                                    yield Static("0", id="overview-errors", classes="metric-value")
                    with Horizontal(id="overview-grid"):
                        with Vertical(classes="panel", id="overview-path-panel"):
                            yield Static("RUN PATH", classes="section-title")
                            yield Static(
                                "1  queued\n2  executing\n3  verifying\n4  evidence ready",
                                id="overview-path",
                                markup=False,
                            )
                        with Vertical(classes="panel", id="overview-events-panel"):
                            yield Static("LATEST EVENTS", classes="section-title")
                            yield Static(
                                "No events yet.",
                                id="overview-recent",
                                markup=False,
                            )
                with Vertical(id="timeline-page", classes="page"):
                    yield Static("EVENT STREAM", id="timeline-heading")
                    yield Static(
                        "Follow the append-only run, then select an event for safe detail.",
                        id="timeline-subtitle",
                    )
                    with Horizontal(id="timeline-workspace"):
                        with Vertical(classes="rail", id="context-rail"):
                            yield Static("RUN CONTEXT", classes="rail-title")
                            kind_val = self._metadata.kind.upper() if self._metadata else "PENDING"
                            case_val = self._metadata.case_id if self._metadata else "pending"
                            yield Static(kind_val, id="kind", classes="metric")
                            yield Static(case_val, id="case", classes="muted")
                            yield Static("RUN ID", classes="rail-title")
                            yield Static("pending", id="run-id", classes="muted")
                            yield Static("ENVIRONMENT", classes="rail-title")
                            yield Static(
                                self._profile_label or "Default",
                                id="profile",
                                classes="muted",
                            )
                            yield Static("TELEMETRY", classes="rail-title")
                            yield Static("Events       0", id="metric-events", classes="metric")
                            yield Static("Turns        0", id="metric-turns", classes="metric")
                            yield Static("Tool calls   0", id="metric-tools", classes="metric")
                            yield Static("Errors       0", id="metric-errors", classes="metric")
                        with Vertical(id="timeline-pane"):
                            yield Input(
                                placeholder="Find an event by type, source, or detail  [ctrl+f]",
                                id="filter",
                            )
                            yield Static(
                                self._render_category_bar_text(),
                                id="category-bar",
                                markup=False,
                            )
                            yield DataTable(id="timeline", cursor_type="row", zebra_stripes=True)
                        with Vertical(classes="rail", id="details-rail"):
                            yield Static("SELECTED EVENT", classes="rail-title")
                            yield Static(
                                "Select an event to see what happened.",
                                id="detail",
                                classes="muted",
                            )
                with Vertical(id="evidence-page", classes="page"):
                    with Horizontal(id="evidence-workspace"):
                        with Vertical(classes="panel", id="evidence-main"):
                            yield Static("EVIDENCE", classes="section-title")
                            yield Static(
                                "A neutral handoff from the live run. Review what "
                                "happened before leaving the workspace.",
                                classes="muted",
                            )
                            yield Static("", id="result")
                            yield Static("OBSERVED SIGNALS", classes="section-title")
                            yield Static(
                                "The run has not completed yet.",
                                id="evidence-observed",
                                markup=False,
                            )
                        with Vertical(classes="panel", id="evidence-side"):
                            yield Static("ARTIFACTS", classes="section-title")
                            yield Static(
                                "Artifacts are created by the run, not by this view.",
                                id="evidence-artifacts",
                                markup=False,
                            )
                            yield Button("Exit to terminal", id="exit", variant="primary")
            yield Static(self._help_text(), id="help-drawer", markup=False)
            yield Footer()

    def on_mount(self) -> None:
        if self._is_config_mode:
            self.query_one("#workspace").display = False
            self.query_one("#status", Label).update("SETUP")
            sc_table = self.query_one("#scenarios-table", DataTable)
            sc_table.add_columns("#", "Simulation", "Group")
            for idx, sc in enumerate(self._scenarios, 1):
                sc_table.add_row(f"{idx:02d}", sc.scenario_id, sc.group, key=sc.scenario_id)
            if self._scenarios:
                self._load_scenario_defaults(self._scenarios[0])
            sc_table.focus()
            return

        self._set_page(WorkspacePage.TIMELINE)
        self._mount_live_timeline()

    def _mount_live_timeline(self) -> None:
        table = self.query_one("#timeline", DataTable)
        table.add_columns("#", "Event", "Source", "Detail")
        table.cursor_type = "row"
        table.focus()
        self.set_interval(1.0, self._update_elapsed)
        self.run_worker(self._run_flow(), exclusive=True, name="simulation")

    def _load_scenario_defaults(self, sc: Scenario) -> None:
        self._selected_scenario = sc
        self.query_one("#scenario", Static).update(sc.name or sc.scenario_id)
        self.query_one("#pipeline-chips", Static).update(f"[{sc.group.upper()}]")
        self.query_one("#setup-copy", Static).update(
            sc.description or "Tune the caller, request, and success signal before launch."
        )
        self.query_one("#input-persona", Input).value = sc.persona
        self.query_one("#input-script", Input).value = sc.script
        self.query_one("#input-goal", Input).value = sc.goal
        self.query_one("#input-turns", Input).value = str(sc.max_turns)
        self.query_one("#input-profile", Input).value = sc.environment_profile
        review = (
            f"Scenario: {sc.scenario_id}\n"
            f"Plugin:   {sc.plugin_id}\n"
            f"Group:    {sc.group}\n"
            f"Profile:  {sc.environment_profile}\n\n"
            "Launch checklist:\n"
            "  Plugin:    selected\n"
            "  Profile:   selected\n"
            "  Artifacts: configured\n"
        )
        self.query_one("#config-review-card", Static).update(review)

    @on(DataTable.RowHighlighted, "#scenarios-table")
    def on_scenario_selected(self, message: DataTable.RowHighlighted) -> None:
        if message.cursor_row < 0 or message.cursor_row >= len(self._scenarios):
            return
        sc = self._scenarios[message.cursor_row]
        self._load_scenario_defaults(sc)

    @on(Button.Pressed, "#btn-launch")
    def on_launch_clicked(self) -> None:
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
                turns = sc.max_turns
        except ValueError:
            turns = sc.max_turns

        profile_id = self.query_one("#input-profile", Input).value or sc.environment_profile
        profile: EnvironmentProfile | None = None
        if self._catalog:
            try:
                profile = self._catalog.environment(profile_id)
            except Exception:
                profile = None
        root_path = Path(profile.artifact_root) if profile else Path("artifacts/user-simulator")
        self._profile_label = profile.label if profile else profile_id

        self._request = FlowRunRequest(
            case_id=sc.plugin_id,
            max_turns=turns,
            root=root_path,
            persona_context=self.query_one("#input-persona", Input).value or None,
            script=self.query_one("#input-script", Input).value or None,
            goal=self.query_one("#input-goal", Input).value or None,
        )

        self.query_one("#kind", Static).update(self._metadata.kind.upper())
        self.query_one("#case", Static).update(self._metadata.case_id)
        self.query_one("#profile", Static).update(self._profile_label)
        self.query_one("#overview-title", Static).update(self._scenario_name)
        self.query_one("#overview-description", Static).update(
            "The live path will appear here as the run moves from request to verified result."
        )
        self.query_one("#config-workspace").display = False
        self.query_one("#workspace").display = True
        self.query_one("#status", Label).update("RUNNING")
        self._is_config_mode = False
        self._started_at = monotonic()
        self._set_page(WorkspacePage.TIMELINE)
        self._mount_live_timeline()

    def on_resize(self, event: Resize) -> None:
        """Preserve the primary task at narrow widths by hiding secondary rails."""
        if self._is_config_mode:
            show_setup_rails = event.size.width > 100
            try:
                self.query_one("#scenarios-rail").display = show_setup_rails
                self.query_one("#config-review-pane").display = show_setup_rails
                self.query_one("#config-form-pane").styles.margin = (
                    0,
                    1 if show_setup_rails else 0,
                )
            except Exception:
                pass
            return
        show_rails = event.size.width > 84
        compact = not show_rails
        try:
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
            evidence_workspace = self.query_one("#evidence-workspace")
            evidence_workspace.styles.layout = "vertical" if compact else "horizontal"
            self.query_one("#evidence-main").styles.width = "1fr" if compact else "2fr"
            self.query_one("#evidence-side").styles.width = "1fr"
            self.query_one("#evidence-main").styles.margin = (0, 0 if compact else 1)
            self.query_one("#evidence-side").styles.margin = (1, 0) if compact else (0, 0)
        except Exception:
            pass

    def _render_page_nav_text(self) -> str:
        """Render the stable page map shown below the run header."""
        if self._active_page is WorkspacePage.SETUP:
            return "SETUP  ·  choose a scenario, tune the request, then launch"
        labels = (
            ("o", WorkspacePage.OVERVIEW, "OVERVIEW"),
            ("t", WorkspacePage.TIMELINE, "TIMELINE"),
            ("e", WorkspacePage.EVIDENCE, "EVIDENCE"),
        )
        items = [
            f"[{key}] {name}" if page is not self._active_page else f"▸ {name}"
            for key, page, name in labels
        ]
        return "  ".join(items) + "  ·  [Tab] next page"

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
        table = self.query_one("#timeline", DataTable)
        table.add_row(
            f"{display.seq:02d}",
            _format_kind_cell(display.kind),
            _format_source_cell(display.source),
            _format_detail_cell(display),
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
        kind_name = display.kind.value.replace("_", " ").upper()
        header = (
            f"EVENT {display.seq:02d}  /  {kind_name}\n"
            f"{display.source.value}  ·  {timestamp}\n"
        )

        text = display.text or "(no display detail)"
        detail = " · ".join(display.detail)
        body = text
        if detail:
            body = f"{body}\n\n{detail}"

        self.query_one("#detail", Static).update(
            f"{header}\n"
            f"{body}\n\n"
            "Sensitive conversation text is not written to the run artifacts."
        )

    def _update_metrics(self) -> None:
        self.query_one("#metric-events", Static).update(f"Events       {len(self._events)}")
        self.query_one("#metric-turns", Static).update(f"Turns        {self._turns}")
        self.query_one("#metric-tools", Static).update(f"Tool calls   {self._tool_calls}")
        self.query_one("#metric-errors", Static).update(f"Errors       {self._errors}")
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
            "\n".join(recent_lines) if recent_lines else "No events yet."
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
        status.update("VERIFIED" if verified else "CHECK RESULT")
        status.remove_class("failed", "review")
        status.add_class("verified" if verified else "review")
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
        self.query_one("#evidence-observed", Static).update(
            f"Outcome      {'verified' if verified else 'needs review'}\n"
            f"End reason   {report.end_reason}\n"
            f"Turns        {report.turns}\n"
            f"Latency      {report.total_latency_ms:.0f} ms\n"
            f"Tokens       {report.total_tokens}"
        )
        self.query_one("#evidence-artifacts", Static).update(
            f"Events\n{result.transcript_path}\n\nReport\n{result.report_path}"
        )
        self.query_one("#overview-activity", Static).update(
            "VERIFIED  /  engine\nThe run is complete. Evidence is ready to review."
            if verified
            else "CHECK RESULT  /  engine\nThe run is complete and needs review."
        )
        self.query_one("#overview-path", Static).update(self._render_run_path())
        self.query_one("#exit", Button).display = True
        self.notify("Run complete. Review any event, then press q to exit.")

    def _set_failed(self, error_name: str) -> None:
        self._finished = True
        self._errors += 1
        self._update_metrics()
        status = self.query_one("#status", Label)
        status.update("FAILED")
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
        self.query_one("#evidence-observed", Static).update(
            f"Outcome      operational failure\n"
            f"Error type   {error_name}\n"
            "The run stopped before a verified result was produced."
        )
        self.query_one("#evidence-artifacts", Static).update(
            "No complete result was produced.\n"
            "Check the run log for the operational failure."
        )
        self.query_one("#overview-activity", Static).update(
            f"FAILED  /  engine\nThe live view stopped before completion ({error_name})."
        )
        self.query_one("#overview-path", Static).update(self._render_run_path())
        self.query_one("#exit", Button).display = True

    def _render_category_bar_text(self) -> str:
        cats = [
            ("[1] ALL", EventCategory.ALL),
            ("[2] DIALOG", EventCategory.DIALOG),
            ("[3] TOOLS", EventCategory.TOOLS),
            ("[4] ERRORS", EventCategory.ERRORS),
            ("[5] STATE", EventCategory.STATE),
        ]
        items: list[str] = []
        for label, cat in cats:
            if cat == self._active_category:
                items.append(f"▸ {label}")
            else:
                items.append(label)
        return "  ".join(items) + "  ·  [?] HELP"

    def _set_active_category(self, cat: EventCategory) -> None:
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
        self._show_help = not self._show_help
        self.query_one("#help-drawer", Static).display = self._show_help

    @staticmethod
    def _help_text() -> str:
        return (
            "KEYBOARD SHORTCUTS\n"
            "  [o] Overview  [t] Timeline  [e] Evidence  [Tab] Next page\n"
            "  [/] or [Ctrl+F] Focus search filter    [Space] Pause / resume view\n"
            "  [Ctrl+L] Clear filter & focus   [1-5] Filter categories\n"
            "  [?] Toggle help drawer          [q] Exit after cleanup"
        )

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_clear_filter(self) -> None:
        field = self.query_one("#filter", Input)
        field.value = ""
        self._active_category = EventCategory.ALL
        self.query_one("#category-bar", Static).update(self._render_category_bar_text())
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
        self.query_one("#status", Label).update(f"RUNNING  {elapsed:02d}s")

    def action_finish(self) -> None:
        if not self._finished and not self._is_config_mode:
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


async def run_interactive_workbench(
    catalog: SimulationCatalog,
    registry: FlowRegistry,
) -> FlowRunResult | None:
    """Run the interactive configuration and execution workbench."""
    app = TextualSimulatorApp(catalog=catalog, registry=registry)
    return await app.run_async()
