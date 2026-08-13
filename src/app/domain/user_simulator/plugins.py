"""Adapter factories that turn the 15 built-in personas into generic flows.

This module is the composition root for the user simulator: it wraps the
existing ``run_support``/``run_reference`` engines behind the generic
``FlowPlugin`` contract and owns the display-safe tool projection registry.
Special logic lives here and in the engine, never in the generic CLI.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping

from app.domain.user_simulator.flows import (
    FlowMetadata,
    FlowPlugin,
    FlowRegistry,
    FlowRunRequest,
    FlowRunResult,
    ProjectedToolCall,
)
from app.domain.user_simulator.personas import (
    REFERENCE_PERSONAS,
    SUPPORT_PERSONAS,
    PersonaDefinition,
)
from app.domain.user_simulator.simulator import (
    ConversationResult,
    run_reference,
    run_support,
)

# ---------------------------------------------------------------------------
# Exact safe tool projection registry
# ---------------------------------------------------------------------------


class ToolProjectionRegistry:
    """Exact per-flow tool projections with a details-hidden fallback.

    ``arguments`` maps flow id -> tool name -> argument keys safe to display;
    ``results`` maps flow id -> tool name -> result fields safe to extract as
    ``field=value`` tokens.  Anything outside the exact maps renders as
    ``details hidden`` so argument values and unrestricted result text never
    leak into the timeline.
    """

    def __init__(
        self,
        arguments: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
        results: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
    ) -> None:
        self._arguments: dict[str, dict[str, tuple[str, ...]]] = {
            flow_id: dict(tools) for flow_id, tools in (arguments or {}).items()
        }
        self._results: dict[str, dict[str, tuple[str, ...]]] = {
            flow_id: dict(tools) for flow_id, tools in (results or {}).items()
        }

    def project(
        self,
        flow_id: str,
        tool: str,
        arguments: Mapping[str, object],
    ) -> ProjectedToolCall:
        visible = self._arguments.get(flow_id, {}).get(tool)
        if visible is None:
            return ProjectedToolCall(
                tool=tool, safe=False, label=f"{tool} (details hidden)"
            )
        shown = ", ".join(
            f"{key}={_short_value(arguments[key])}" for key in visible if key in arguments
        )
        label = f"{tool}({shown})" if shown else f"{tool}()"
        return ProjectedToolCall(tool=tool, safe=True, label=label)

    def project_result(self, flow_id: str, tool: str, result: str) -> str:
        """Project a tool result to a short safe summary (never raw text)."""
        fields = self._results.get(flow_id, {}).get(tool, ())
        if fields:
            parts: list[str] = []
            for field in fields:
                match = re.search(rf"\b{re.escape(field)}=([^\s,;]+)", result)
                if match:
                    parts.append(f"{field}={_short_value(match.group(1))}")
            if parts:
                return ", ".join(parts)
        return "(result details hidden)"


def _short_value(value: object) -> str:
    text = " ".join(str(value).split())
    if len(text) <= 160:
        return text
    return text[:159] + "…"


_SUPPORT_TOOLS: dict[str, tuple[str, ...]] = {
    "get_order_status": ("order_id",),
    "get_policy": (),
    "propose_refund": ("order_id",),
    "confirm_refund": ("order_id",),
    "escalate": (),
}

_REFERENCE_TOOLS: dict[str, dict[str, tuple[str, ...]]] = {
    "flight_booking": {
        "search_flights": ("origin", "destination"),
        "get_fare": ("flight_id",),
        "hold_booking": ("flight_id",),
        "confirm_booking": ("pnr",),
        "cancel_booking": ("pnr",),
    },
    "incident_response": {
        "get_service_status": ("service_id",),
        "find_runbook": ("terms",),
        "run_remediation_step": ("step",),
        "page_on_call": ("engineer",),
        "ack_incident": ("incident_id",),
    },
    "ci_triage": {
        "read_failing_checks": ("pr",),
        "read_test_logs": ("run",),
        "search_known_issues": ("test",),
        "open_triage_issue": ("kind",),
        "create_fix_branch": ("test",),
    },
    "claims_denial": {
        "get_claim": ("claim_id",),
        "retrieve_policy": ("version",),
        "get_clinical_notes": ("claim_id",),
        "save_appeal_draft": ("claim_id", "policy_version"),
        "submit_appeal": ("draft",),
    },
    "returns_resolution": {
        "get_order": ("order_id",),
        "verify_order_ownership": ("order_id",),
        "get_return_policy": ("version",),
        "approve_return": ("order_id",),
        "process_refund": ("order_id",),
    },
    "onboarding": {
        "get_candidate": ("candidate_id",),
        "get_position": ("position_id",),
        "select_checklist": ("source",),
        "create_worker_record": ("candidate_id",),
        "complete_task": ("task",),
    },
    "disputes": {
        "get_account": ("account_id",),
        "get_transaction": ("transaction_id",),
        "get_fraud_signals": ("transaction_id",),
        "open_dispute": ("transaction_id",),
        "provisional_credit": ("evidence_minimum",),
    },
}

_SUPPORT_RESULTS: dict[str, tuple[str, ...]] = {
    "get_order_status": (),
    "get_policy": (),
    "propose_refund": (),
    "confirm_refund": (),
    "escalate": (),
}

_REFERENCE_RESULTS: dict[str, dict[str, tuple[str, ...]]] = {
    "flight_booking": {
        "hold_booking": ("pnr", "fare"),
        "confirm_booking": ("pnr",),
        "cancel_booking": ("pnr",),
    },
    "incident_response": {},
    "ci_triage": {},
    "claims_denial": {},
    "returns_resolution": {},
    "onboarding": {},
    "disputes": {},
}

SUPPORT_PROJECTOR = ToolProjectionRegistry(
    {persona.scenario_or_workflow_id: _SUPPORT_TOOLS for persona in SUPPORT_PERSONAS},
    results={
        persona.scenario_or_workflow_id: _SUPPORT_RESULTS for persona in SUPPORT_PERSONAS
    },
)
REFERENCE_PROJECTOR = ToolProjectionRegistry(_REFERENCE_TOOLS, results=_REFERENCE_RESULTS)

# ---------------------------------------------------------------------------
# Plugin factories
# ---------------------------------------------------------------------------


class _FlowPlugin:
    """One registered flow: metadata plus an async runner."""

    def __init__(
        self,
        metadata: FlowMetadata,
        run: Callable[[FlowRunRequest], Awaitable[FlowRunResult]],
    ) -> None:
        self.metadata = metadata
        self._run = run

    async def run(self, request: FlowRunRequest) -> FlowRunResult:
        return await self._run(request)

def _to_flow_result(result: ConversationResult) -> FlowRunResult:
    return FlowRunResult(
        report=result.report,
        transcript_path=result.transcript_path,
        report_path=result.report_path,
    )


def _apply_overrides(
    persona: PersonaDefinition, request: FlowRunRequest
) -> PersonaDefinition:
    """Apply wizard/flag persona overrides to one persona definition."""
    updates: dict[str, str] = {}
    if request.persona_context is not None:
        updates["persona"] = request.persona_context
    if request.script is not None:
        updates["script"] = request.script
    if request.goal is not None:
        updates["goal"] = request.goal
    if not updates:
        return persona
    return persona.model_copy(update=updates)


def support_plugin(persona: PersonaDefinition) -> FlowPlugin:
    """Wrap one support persona behind the generic flow contract.

    The selected profile's disposable database URL (from
    ``request.runtime.database_url``) is injected into the engine, so the run
    never falls back to unrelated DATABASE_URL configuration.
    """

    async def run(request: FlowRunRequest) -> FlowRunResult:
        result = await run_support(
            _apply_overrides(persona, request),
            max_turns=request.max_turns,
            root=request.root,
            event_sink=request.sink,
            tool_projector=SUPPORT_PROJECTOR,
            database_url=request.runtime.database_url if request.runtime else None,
        )
        return _to_flow_result(result)

    return _FlowPlugin(
        metadata=FlowMetadata(
            flow_id=persona.persona_id,
            case_id=persona.persona_id,
            kind="support",
            name=persona.goal[:120],
            description=persona.goal,
        ),
        run=run,
    )


def reference_plugin(persona: PersonaDefinition) -> FlowPlugin:
    """Wrap one reference persona behind the generic flow contract."""

    async def run(request: FlowRunRequest) -> FlowRunResult:
        result = await run_reference(
            _apply_overrides(persona, request),
            max_turns=request.max_turns,
            root=request.root,
            event_sink=request.sink,
            tool_projector=REFERENCE_PROJECTOR,
        )
        return _to_flow_result(result)

    return _FlowPlugin(
        metadata=FlowMetadata(
            flow_id=persona.persona_id,
            case_id=persona.persona_id,
            kind="reference",
            name=persona.goal[:120],
            description=persona.goal,
        ),
        run=run,
    )


def builtin_plugin_factory() -> tuple[FlowPlugin, ...]:
    """Build the 15 built-in plugins (eight support, seven reference)."""
    return tuple(support_plugin(persona) for persona in SUPPORT_PERSONAS) + tuple(
        reference_plugin(persona) for persona in REFERENCE_PERSONAS
    )


def build_default_registry() -> FlowRegistry:
    """Create a registry with the 15 built-in plugins."""
    registry = FlowRegistry()
    for plugin in builtin_plugin_factory():
        registry.register(plugin)
    return registry
