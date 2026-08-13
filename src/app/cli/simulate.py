"""Generic ``lab simulate`` CLI: setup wizard + events + Rich timeline.

This module deliberately contains no support- or reference-specific code and
no hardcoded flow ids or tools.  It drives any registered ``FlowPlugin``
through a versioned YAML catalog (see ``catalog.py``), a setup wizard, a
preflight gate, and one append-only operational timeline.

Subcommands (repo-style nested shape):

- ``lab simulate list``       grouped catalog listing
- ``lab simulate validate``   strict YAML validation
- ``lab simulate run <id>``   guided setup + preflight + live run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, cast

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from app.domain.user_simulator.events import (
    DisplayEvent,
    EventKind,
    EventSink,
    SimulationEvent,
)
from app.domain.user_simulator.flows import (
    FlowMetadata,
    FlowPersonaDefaults,
    FlowPersonaProvider,
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
    load_simulation_catalog,
)
from app.domain.user_simulator.preflight import (
    EnvironmentProfileLike,
    resolve_runtime,
    run_preflight,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130
TIMELINE_WIDTH = 80
MAX_VALUE_CHARS = 160
REASONING_UNAVAILABLE = "(reasoning unavailable)"
DEFAULT_ROOT = "artifacts/user-simulator"
DEFAULT_CATALOG_ROOT = "simulations"

_LABELS = {
    EventKind.START: "start",
    EventKind.USER: "user",
    EventKind.AGENT: "agent",
    EventKind.MODEL: "model",
    EventKind.TOOL_SELECTED: "tool selected",
    EventKind.TOOL_RESULT: "tool result",
    EventKind.APPROVAL: "approval",
    EventKind.RETRY: "retry",
    EventKind.STATE: "state",
    EventKind.DONE: "done",
    EventKind.ERROR: "error",
    EventKind.CLEANUP: "cleanup",
}

_STYLES = {
    EventKind.START: "bold cyan",
    EventKind.USER: "bold blue",
    EventKind.AGENT: "bold green",
    EventKind.MODEL: "cyan",
    EventKind.TOOL_SELECTED: "magenta",
    EventKind.TOOL_RESULT: "magenta",
    EventKind.APPROVAL: "bold yellow",
    EventKind.RETRY: "yellow",
    EventKind.STATE: "bright_black",
    EventKind.DONE: "bold green",
    EventKind.ERROR: "bold red",
    EventKind.CLEANUP: "dim",
}

_TOOL_KINDS = frozenset({EventKind.TOOL_SELECTED, EventKind.TOOL_RESULT})


# ---------------------------------------------------------------------------
# Value rendering
# ---------------------------------------------------------------------------


def escape_value(value: str) -> str:
    """Escape control characters so timeline values are terminal-safe."""
    characters = []
    for char in value:
        if char.isprintable():
            characters.append(char)
        elif char == "\n":
            characters.append("\\n")
        elif char == "\t":
            characters.append("\\t")
        elif char == "\r":
            characters.append("\\r")
        else:
            characters.append(f"\\x{ord(char):02x}")
    return "".join(characters)


def short_value(value: str) -> str:
    """Collapse whitespace, escape, and cap one value at 160 characters."""
    flat = escape_value(" ".join(value.split()))
    if len(flat) <= MAX_VALUE_CHARS:
        return flat
    return flat[: MAX_VALUE_CHARS - 1] + "…"


def _fit(value: str, width: int) -> str:
    """Truncate one line to ``width`` characters with an ellipsis."""
    if len(value) <= width:
        return value
    return value[: max(width - 1, 0)] + "…"


def _label_of(kind: EventKind) -> str:
    return _LABELS.get(kind, kind.value)


def _model_text(text: str) -> str:
    """Append the fixed reasoning-unavailable note; chain-of-thought is never shown."""
    base = text or "model response"
    return f"{base} {REASONING_UNAVAILABLE}"


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------


class RichTimelineSink:
    """One append-only operational timeline at 80 columns with semantic colors."""

    def __init__(self, metadata: FlowMetadata, console: Console | None = None) -> None:
        self._metadata = metadata
        self._console = console or Console(highlight=False, width=TIMELINE_WIDTH)
        self._header_shown = False
        self.run_id: str | None = None

    def emit(self, event: SimulationEvent) -> None:
        display = event.display
        if display is None:
            return
        if not self._header_shown:
            self._header_shown = True
            self._print_header(display)
        self._print_line(display)

    def _print_header(self, first: DisplayEvent) -> None:
        detail = dict(line.split("=", 1) for line in first.detail if "=" in line)
        run_id = detail.get("run_id", "")
        if run_id:
            self.run_id = run_id
        jsonl_path = detail.get("jsonl_path", "")
        report_path = detail.get("report_path", "")
        inner = TIMELINE_WIDTH - 4  # panel borders plus padding
        metadata = self._metadata
        name = short_value(metadata.name)[:30]
        title_line = f"case {metadata.case_id} · {metadata.kind}"
        if name:
            title_line += f" · {name}"
        title_line = _fit(title_line, inner)
        run_line = f"run {short_value(run_id) if run_id else '?'}"
        if jsonl_path:
            run_line += f" · jsonl {short_value(jsonl_path)}"
        run_line = _fit(run_line, inner)
        report_line = _fit(f"report {short_value(report_path)}", inner)
        body = Text()
        body.append(title_line, style="bold")
        body.append("\n")
        run_text = Text(run_line)
        if run_id:
            run_text.stylize("cyan", 4, 4 + len(short_value(run_id)))
        body.append(run_text)
        body.append("\n")
        body.append(Text(report_line, style="dim"))
        self._console.print(
            Panel(
                body,
                title="USER SIMULATOR",
                border_style="dim",
                width=TIMELINE_WIDTH,
                expand=True,
            )
        )

    def _print_line(self, display: DisplayEvent) -> None:
        label = _label_of(display.kind)
        style = _STYLES.get(display.kind, "")
        indent = "  " if display.kind in _TOOL_KINDS else ""
        text = display.text or ""
        if display.kind is EventKind.MODEL:
            text = _model_text(text)
        prefix = f"{indent}{display.seq:>3} "
        label_width = max(len(label), 8)
        text_width = TIMELINE_WIDTH - len(prefix) - label_width - 1
        value = short_value(text)
        if len(value) > text_width:
            value = value[: max(text_width - 1, 0)] + "…"
        line = Text()
        line.append(prefix, style="dim")
        line.append(f"{label:<{label_width}} ", style=style)
        line.append(value)
        self._console.print(line, no_wrap=True, overflow="ignore")


class PlainEventSink:
    """Non-TTY / ``--no-live`` mode: one plain line per event, ready for tailing."""

    def __init__(self) -> None:
        self.run_id: str | None = None

    def emit(self, event: SimulationEvent) -> None:
        display = event.display
        if display is None:
            return
        if display.kind is EventKind.START:
            for line in display.detail:
                if line.startswith("run_id="):
                    self.run_id = line.split("=", 1)[1]
                print(line, flush=True)
        text = display.text or ""
        if display.kind is EventKind.MODEL:
            text = _model_text(text)
        print(
            f"[{display.seq}] {display.source.value.upper()} "
            f"{_label_of(display.kind)} {short_value(text)}",
            flush=True,
        )


class _SilentSink:
    """Discards output but records run identity; used with --json.

    stdout stays pure JSON while the run id is still observable so an
    interrupt can report the observed cleanup status from the JSONL log.
    """

    def __init__(self) -> None:
        self.run_id: str | None = None

    def emit(self, event: SimulationEvent) -> None:
        display = event.display
        if display is None or display.kind is not EventKind.START:
            return
        for line in display.detail:
            if line.startswith("run_id="):
                self.run_id = line.split("=", 1)[1]


# ---------------------------------------------------------------------------
# Setup state
# ---------------------------------------------------------------------------


@dataclass
class EffectiveSetup:
    """The resolved setup: scenario defaults plus wizard/flag overrides."""

    plugin: FlowPlugin
    scenario: Scenario
    persona: str
    script: str
    goal: str
    max_turns: int


def _fail(code: str, message: str, *, args: argparse.Namespace | None = None) -> NoReturn:
    """Fail with a stable error; machine-readable JSON on stdout in JSON mode."""
    if args is not None and getattr(args, "json", False):
        print(
            json.dumps(
                {"ok": False, "error": {"code": code, "message": message}},
                indent=2,
            )
        )
    else:
        print(f"lab: error [{code}]: {message}", file=sys.stderr)
    raise SystemExit(EXIT_ERROR)


def _is_live(args: argparse.Namespace, override: bool | None) -> bool:
    if override is not None:
        return override
    return not getattr(args, "no_live", False) and sys.stdout.isatty()


def _interactive(args: argparse.Namespace, live: bool) -> bool:
    return live and not args.yes and sys.stdin.isatty()


def _build_catalog(
    args: argparse.Namespace, registry: FlowRegistry
) -> SimulationCatalog:
    """Load scenarios through the manifests loader (single source of truth)."""
    root = Path(getattr(args, "catalog_root", DEFAULT_CATALOG_ROOT))
    paths = tuple(sorted(root.glob("*.yaml"))) if root.is_dir() else ()
    known = {plugin.metadata.flow_id for plugin in registry.all()}
    return load_simulation_catalog(paths, known_plugin_ids=known)


def _env_for_preflight() -> dict[str, str]:
    """Merge the process environment with .env so preflight matches the engine."""
    values = dict(os.environ)
    try:
        from dotenv import dotenv_values

        for key, value in dotenv_values(".env").items():
            if value is not None and key not in values:
                values[key] = value
    except Exception:
        pass
    return values


def _persona_defaults(plugin: FlowPlugin) -> FlowPersonaDefaults:
    if isinstance(plugin, FlowPersonaProvider):
        return plugin.persona_defaults()
    return FlowPersonaDefaults()


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _cmd_list_json(catalog: SimulationCatalog) -> int:
    """Machine-readable catalog listing (one stable JSON object, no stderr)."""
    group_counts: dict[str, int] = {}
    scenario_payloads: list[dict[str, object]] = []
    for scenario in catalog.scenarios:
        group_counts[scenario.group] = group_counts.get(scenario.group, 0) + 1
        scenario_payloads.append(
            {
                "scenario_id": scenario.scenario_id,
                "plugin_id": scenario.plugin_id,
                "group": scenario.group,
                "name": scenario.name,
                "description": scenario.description,
                "max_turns": scenario.max_turns,
                "environment_profile": scenario.environment_profile,
            }
        )
    print(
        json.dumps(
            {
                "ok": True,
                "catalog_count": len(group_counts),
                "catalogs": {
                    group: {"count": count}
                    for group, count in sorted(group_counts.items())
                },
                "simulations": scenario_payloads,
            },
            indent=2,
        )
    )
    return EXIT_OK


def _cmd_list(args: argparse.Namespace, live: bool) -> int:
    registry: FlowRegistry = args.registry
    registry.ensure_builtins()
    catalog = _build_catalog(args, registry)
    if not catalog.ok:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "issues": list(catalog.validate())}, indent=2))
        else:
            print("simulation setup is invalid:", file=sys.stderr)
            for issue in catalog.issues:
                print(f"  {issue}", file=sys.stderr)
        return EXIT_ERROR
    if getattr(args, "json", False):
        return _cmd_list_json(catalog)
    scenarios = catalog.scenarios
    if not scenarios:
        print("no simulations configured (add YAML catalogs under simulations/)")
        return EXIT_OK
    groups: dict[str, list[Scenario]] = {}
    for scenario in scenarios:
        groups.setdefault(scenario.group, []).append(scenario)
    if live:
        console = Console(highlight=False)
        console.print(Text("USER SIMULATOR — simulations", style="bold cyan"))
        for group in sorted(groups):
            console.print(Text(group, style="bold"))
            for scenario in groups[group]:
                console.print(
                    f"  {scenario.scenario_id:<44} {scenario.name or scenario.plugin_id}  "
                    f"[dim](profile {scenario.environment_profile}, "
                    f"{scenario.max_turns} turns)[/dim]"
                )
    else:
        for group in sorted(groups):
            print(f"[{group}]")
            for scenario in groups[group]:
                print(
                    f"  {scenario.scenario_id}  {scenario.name or scenario.plugin_id}  "
                    f"profile={scenario.environment_profile} turns={scenario.max_turns}"
                )
    return EXIT_OK


def _cmd_validate(args: argparse.Namespace, live: bool) -> int:
    del live
    registry: FlowRegistry = args.registry
    registry.ensure_builtins()
    catalog = _build_catalog(args, registry)
    issues = catalog.validate()
    if getattr(args, "json", False):
        payload = {
            "ok": not issues,
            "simulations": len(catalog.scenarios),
            "environments": len(catalog.environments()),
            "issues": list(issues),
        }
        print(json.dumps(payload, indent=2))
        return EXIT_OK if not issues else EXIT_ERROR
    if issues:
        print("simulation setup is invalid:", file=sys.stderr)
        for issue in issues:
            print(f"  {issue}", file=sys.stderr)
        return EXIT_ERROR
    print(
        f"validated {len(catalog.scenarios)} simulation(s) and "
        f"{len(catalog.environments())} environment profile(s)"
    )
    return EXIT_OK


def _choose_scenario(
    console: Console, catalog: SimulationCatalog
) -> Scenario | None:
    """Grouped, keyboard-friendly numbered chooser; returns None on cancel."""
    scenarios = catalog.scenarios
    if not scenarios:
        console.print(
            "[bold]No simulations configured.[/bold] Add YAML catalogs under "
            "simulations/ and register their plugins."
        )
        return None
    rows: list[Scenario] = []
    table = Table(
        title="Choose a simulation",
        box=None,
        width=TIMELINE_WIDTH,
        highlight=True,
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("simulation", style="bold")
    table.add_column("group", style="cyan")
    table.add_column("profile", style="magenta")
    table.add_column("turns", justify="right")
    for scenario in scenarios:
        rows.append(scenario)
        table.add_row(
            str(len(rows)),
            f"{scenario.scenario_id} — {scenario.name or scenario.plugin_id}",
            scenario.group,
            scenario.environment_profile,
            str(scenario.max_turns),
        )
    console.print(table)
    choices = [str(index) for index in range(1, len(rows) + 1)] + ["q", "cancel"]
    choice = Prompt.ask(
        "Choose a simulation (number), or q to cancel",
        choices=choices,
        default="1",
        console=console,
    )
    if choice in {"q", "cancel"}:
        return None
    return rows[int(choice) - 1]


def _wizard_edit(
    console: Console,
    args: argparse.Namespace,
    effective: EffectiveSetup,
    profile: EnvironmentProfile,
    catalog: SimulationCatalog,
) -> tuple[EffectiveSetup, EnvironmentProfile] | None:
    """Interactive edit + review loop; returns None when the user cancels."""
    while True:
        persona = Prompt.ask(
            "persona context",
            default=effective.persona or "(none)",
            console=console,
        )
        script = Prompt.ask("script", default=effective.script or "(none)", console=console)
        goal = Prompt.ask("goal", default=effective.goal or "(none)", console=console)
        turns = Prompt.ask(
            "max turns", default=str(effective.max_turns), console=console
        )
        try:
            max_turns = int(turns)
            if not 1 <= max_turns <= 50:
                raise ValueError
        except ValueError:
            _fail(
                "max_turns_out_of_range",
                "max turns must be an integer from 1 to 50",
                args=args,
            )
        selected_profile = profile
        if args.profile is None:
            profiles = list(catalog.environments())
            rows = {str(index): item for index, item in enumerate(profiles, 1)}
            console.print(Text("Environment profiles", style="bold cyan"))
            for index, item in enumerate(profiles, 1):
                console.print(f"  {index}. {item.label}  [dim]({item.profile_id})[/dim]")
            current = next(
                (str(index) for index, item in enumerate(profiles, 1)
                 if item.profile_id == profile.profile_id),
                "1",
            )
            choice = Prompt.ask(
                "Choose an environment profile",
                choices=list(rows) + ["q"],
                default=current,
                console=console,
            )
            if choice == "q":
                return None
            selected_profile = rows[choice]
        updated = EffectiveSetup(
            plugin=effective.plugin,
            scenario=effective.scenario,
            persona=persona if persona != "(none)" else "",
            script=script if script != "(none)" else "",
            goal=goal if goal != "(none)" else "",
            max_turns=max_turns,
        )
        _print_review(console, updated, selected_profile)
        confirm = Prompt.ask(
            "Start the simulation? [y/N]",
            choices=["y", "n", "q", "back"],
            default="n",
            console=console,
        )
        if confirm == "y":
            return updated, selected_profile
        if confirm in {"q", "cancel"}:
            return None
        # "n" or "back": restart the edit loop


def _review_lines(setup: EffectiveSetup, profile: EnvironmentProfile) -> list[str]:
    metadata = setup.plugin.metadata
    model_values = _env_for_preflight()
    model = (
        f"{profile.model_provider or model_values.get('MODEL_PROVIDER', '?')}/"
        f"{profile.model_name or model_values.get('MODEL_NAME', '?')}"
    )
    host = profile.db_host or "?"
    port = profile.db_port or "?"
    db = profile.db_name or "?"
    return [
        f"plugin     {metadata.flow_id} ({metadata.kind})",
        f"name       {setup.scenario.name or metadata.name}",
        f"model      {model}",
        f"database   {host}:{port}/{db} (profile {profile.profile_id})",
        f"env        {profile.environment}",
        f"artifacts  {profile.artifact_root}",
        f"rollback   {profile.isolation_policy} (loopback only: "
        f"{'yes' if profile.loopback_only else 'no'})",
        f"turns      {setup.max_turns}",
    ]


def _print_review(
    console: Console,
    setup: EffectiveSetup,
    profile: EnvironmentProfile,
    *,
    plain: bool = False,
) -> None:
    if plain:
        print("setup review")
        for line in _review_lines(setup, profile):
            print(f"  {line}", flush=True)
        return
    body = Text()
    for line in _review_lines(setup, profile):
        body.append(line)
        body.append("\n")
    console.print(
        Panel(body, title="Setup review", border_style="dim", width=TIMELINE_WIDTH)
    )


async def _cmd_run(args: argparse.Namespace, live: bool) -> int:
    registry: FlowRegistry = args.registry
    registry.ensure_builtins()
    catalog = _build_catalog(args, registry)
    if not catalog.ok:
        if getattr(args, "json", False):
            print(
                json.dumps({"ok": False, "issues": list(catalog.validate())}, indent=2)
            )
        else:
            print("simulation setup is invalid; fix the YAML files first:", file=sys.stderr)
            for problem in catalog.issues:
                print(f"  {problem}", file=sys.stderr)
        return EXIT_ERROR
    use_live = _is_live(args, live)
    interactive = _interactive(args, use_live)
    console = Console(highlight=False, no_color=not use_live)

    scenario: Scenario | None = None
    if args.simulation_id:
        try:
            scenario = catalog.get(args.simulation_id)
        except CatalogError as error:
            available = ", ".join(
                s.scenario_id for s in catalog.scenarios
            ) or "(none)"
            _fail(
                "simulation_not_found",
                f"{error}; available: {available}",
                args=args,
            )
    elif interactive:
        scenario = _choose_scenario(console, catalog)
        if scenario is None:
            print("setup cancelled; no artifacts were created")
            return EXIT_OK
    else:
        _fail(
            "simulation_required",
            "specify a simulation id (see 'lab simulate list'), or run on a terminal",
            args=args,
        )

    plugin = registry.get(scenario.plugin_id)
    defaults = _persona_defaults(plugin)
    effective = EffectiveSetup(
        plugin=plugin,
        scenario=scenario,
        persona=args.persona or scenario.persona or defaults.persona,
        script=args.script or scenario.script or defaults.script,
        goal=args.goal or scenario.goal or defaults.goal,
        max_turns=args.max_turns or scenario.max_turns,
    )
    if not 1 <= effective.max_turns <= 50:
        _fail(
            "max_turns_out_of_range",
            "max turns must be an integer from 1 to 50",
            args=args,
        )
    profile_id = args.profile or scenario.environment_profile
    try:
        profile = catalog.environment(profile_id)
    except CatalogError as error:
        _fail("profile_not_found", str(error), args=args)

    if interactive:
        edited = _wizard_edit(console, args, effective, profile, catalog)
        if edited is None:
            print("setup cancelled; no artifacts were created")
            return EXIT_OK
        effective, profile = edited
    else:
        # Non-interactive: still show the review once when not --json.
        if not getattr(args, "json", False):
            _print_review(console, effective, profile, plain=not use_live)

    env = _env_for_preflight()
    issues = await run_preflight(
        plugin_id=scenario.plugin_id,
        registry=registry,
        profile=cast("EnvironmentProfileLike", profile),
        env=env,
    )
    if issues:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "issues": [
                            {"name": i.name, "message": i.message, "fix": i.fix}
                            for i in issues
                        ],
                    },
                    indent=2,
                )
            )
        else:
            print("setup check failed; nothing was started:", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
        return EXIT_ERROR

    runtime, runtime_issues = resolve_runtime(
        cast("EnvironmentProfileLike", profile), env
    )
    if runtime_issues:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "profile_refused",
                            "message": "; ".join(
                                str(issue) for issue in runtime_issues
                            ),
                        },
                    },
                    indent=2,
                )
            )
        else:
            print("selected profile refused; nothing was started:", file=sys.stderr)
            for issue in runtime_issues:
                print(f"  - {issue}", file=sys.stderr)
        return EXIT_ERROR

    sink = _build_sink(plugin.metadata, args, use_live)
    request = FlowRunRequest(
        case_id=scenario.plugin_id,
        max_turns=effective.max_turns,
        root=Path(profile.artifact_root),
        sink=sink,
        persona_context=effective.persona or None,
        script=effective.script or None,
        goal=effective.goal or None,
        runtime=runtime,
    )
    args._sink = sink
    args._artifact_root = profile.artifact_root
    result = await plugin.run(request)
    _print_final(result, args, use_live)
    return EXIT_OK


def _build_sink(metadata: FlowMetadata, args: argparse.Namespace, live: bool) -> EventSink:
    if getattr(args, "json", False):
        return _SilentSink()
    if live:
        return RichTimelineSink(metadata)
    return PlainEventSink()


def _print_final(
    result: FlowRunResult,
    args: argparse.Namespace,
    live: bool,
) -> None:
    report = result.report
    if getattr(args, "json", False):
        print(report.model_dump_json(indent=2))
        return
    status = "verified" if report.verified_goal else "not verified"
    line = (
        f"status: {report.end_reason} ({status}) · {report.turns} turns · "
        f"{report.total_tokens} tokens"
    )
    if report.cost_usd is not None:
        line += f" · cost ${report.cost_usd:.4f}"
    if live:
        Console(highlight=False).print(Text(line, style="bold green"))
    else:
        print(line, flush=True)
    print(f"run_id={report.run_id}", flush=True)
    print(f"jsonl_path={result.transcript_path}", flush=True)
    print(f"report_path={result.report_path}", flush=True)


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


async def _dispatch(args: argparse.Namespace, *, live: bool | None = None) -> int:
    command = getattr(args, "simulate_command", "run")
    use_live = _is_live(args, live)
    if command == "list":
        return _cmd_list(args, use_live)
    if command == "validate":
        return _cmd_validate(args, use_live)
    return await _cmd_run(args, use_live)


def _cleanup_status(root: Path, run_id: str | None) -> str | None:
    """Read the observed cleanup status from the run's persistent JSONL.

    Returns ``None`` when no cleanup event was observed, ``rollback`` (or the
    event's own reason) when cleanup succeeded, or ``cleanup_failed`` when the
    engine reported a cleanup failure.  The partial report is written before
    cleanup, so only this event proves cleanup happened.
    """
    if not run_id:
        return None
    path = root / f"{run_id}.jsonl"
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == "cleanup":
            return str(payload.get("reason", "rollback"))
    return None


def _interrupt_exit(args: argparse.Namespace) -> int:
    """Report the observed cleanup status after an interrupt, never a guess.

    The message keys to the cleanup event written by the engine only after a
    successful rollback/destroy; a missing or failed marker says so and the
    process still exits nonzero.  Works in normal, plain, and ``--json`` modes
    because the persistent JSONL is always written.
    """
    sink = getattr(args, "_sink", None)
    run_id = getattr(sink, "run_id", None) if sink is not None else None
    root = Path(getattr(args, "_artifact_root", DEFAULT_ROOT))
    status = _cleanup_status(root, run_id)
    if status == "cleanup_failed":
        message = (
            "Simulation interrupted (Ctrl-C). Cleanup FAILED; see the run log."
        )
        code = EXIT_ERROR
    elif status is not None:
        message = (
            "Simulation interrupted (Ctrl-C). Cleanup and rollback complete "
            "(observed)."
        )
        code = EXIT_INTERRUPTED
    else:
        message = (
            "Simulation interrupted (Ctrl-C). Cleanup status unknown; no cleanup "
            "event observed."
        )
        code = EXIT_INTERRUPTED
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "interrupted",
                        "message": message,
                        "cleanup": status or "unknown",
                    }
                },
                indent=2,
            )
        )
    else:
        print(message, file=sys.stderr)
    return code


def cmd_simulate(args: argparse.Namespace) -> NoReturn:
    """``lab simulate`` handler entry; exits with a status code."""
    try:
        code = asyncio.run(_dispatch(args, live=getattr(args, "live", None)))
    except KeyboardInterrupt:
        code = _interrupt_exit(args)
    raise SystemExit(code)


def build_simulate_parser(
    parser: argparse.ArgumentParser, registry: FlowRegistry
) -> None:
    """Add the ``simulate`` subcommand arguments and wire its handler."""
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print stable structured output",
    )
    sub = parser.add_subparsers(dest="simulate_command", required=True)

    run = sub.add_parser("run", help="guided setup + preflight + live run")
    run.add_argument("simulation_id", nargs="?", help="simulation id (see list)")
    run.add_argument("--profile", default=None, help="environment profile id")
    run.add_argument(
        "--max-turns", type=int, default=None, help="maximum conversation turns (1-50)"
    )
    run.add_argument("--persona", default=None, help="override persona context")
    run.add_argument("--script", default=None, help="override persona script")
    run.add_argument("--goal", default=None, help="override persona goal")
    run.add_argument(
        "--yes", action="store_true", help="skip interactive prompts; fail if missing"
    )
    run.add_argument(
        "--no-live", action="store_true", help="plain one-line events even on a terminal"
    )
    run.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS,
        help="print stable structured output",
    )
    run.set_defaults(
        func=cmd_simulate, registry=registry, simulate_command="run"
    )

    listing = sub.add_parser("list", help="grouped catalog listing")
    listing.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS,
        help="print stable structured output",
    )
    listing.set_defaults(
        func=cmd_simulate, registry=registry, simulate_command="list"
    )

    validate = sub.add_parser("validate", help="strict YAML validation")
    validate.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS,
        help="print stable structured output",
    )
    validate.set_defaults(
        func=cmd_simulate, registry=registry, simulate_command="validate"
    )


def run_simulate(
    argv: Sequence[str],
    *,
    registry: FlowRegistry,
    live: bool | None = None,
    catalog_root: Path = Path(DEFAULT_CATALOG_ROOT),
) -> int:
    """Run the simulate CLI with an explicit registry; returns an exit code.

    ``catalog_root`` selects the directory of grouped YAML scenario catalogs;
    environment profiles always come from the loader's own file.
    """
    parser = argparse.ArgumentParser(
        prog="lab", description="Agent simulation lab workflow over the Phase 7 services."
    )
    parser.add_argument("--json", action="store_true", help="print stable structured output")
    sub = parser.add_subparsers(dest="command", required=True)
    simulate = sub.add_parser("simulate", help="run one registered user-simulator flow")
    build_simulate_parser(simulate, registry)
    args = parser.parse_args(list(argv))
    args.catalog_root = Path(catalog_root)
    try:
        return asyncio.run(_dispatch(args, live=live))
    except KeyboardInterrupt:
        return _interrupt_exit(args)
