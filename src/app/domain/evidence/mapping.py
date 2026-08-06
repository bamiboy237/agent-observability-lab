"""This module maps one normalized run tree into TraceEvidence.

Adapters parse provider records into :class:`SourceRun` nodes.
This module validates and aggregates the tree with no provider knowledge.
Provider-specific attributes stay outside this module.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from app.domain.evidence.errors import InvalidEvidence, UnsupportedTrace
from app.domain.evidence.models import stable_evidence_id
from app.domain.evidence.schemas import (
    TASK_INPUT_ALLOWLIST,
    TASK_OUTPUT_ALLOWLIST,
    ConfirmationDecision,
    DependencyCall,
    PolicyDecision,
    RedactionMetadata,
    Scalar,
    TokenUsage,
    TraceEvent,
    TraceEventKind,
    TraceEvidence,
    TraceModelRef,
    TraceOutcome,
    TraceSourceRef,
    TurnTiming,
)
from app.telemetry.allowlist import TRACE_ATTRIBUTE_ALLOWLIST

_KIND_PREFIXES: tuple[tuple[str, TraceEventKind], ...] = (
    ("support_agent.turn", TraceEventKind.TURN),
    ("support_agent.routing", TraceEventKind.ROUTING),
    ("support_agent.answer", TraceEventKind.ANSWER),
    ("support_agent.tool.", TraceEventKind.TOOL),
    ("support_agent.database.", TraceEventKind.DATABASE),
    ("support_agent.retrieval.", TraceEventKind.RETRIEVAL),
    ("support_agent.policy.", TraceEventKind.POLICY),
    ("support_agent.confirmation", TraceEventKind.CONFIRMATION),
    ("support_agent.escalation", TraceEventKind.ESCALATION),
    ("support_agent.retry", TraceEventKind.RETRY),
)

_SENSITIVE_ATTRIBUTE_PARTS = (
    "api_key",
    "secret",
    "password",
    "token",
    "authorization",
    "credential",
    "credit",
    "ssn",
    "email",
    "phone",
    "message",
)

_STABLE_ERROR_CODE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class SourceRun:
    """This class stores one provider record after extraction.

    Adapters build this neutral shape from provider JSON.
    The list must be in pre-order: every parent precedes its children.
    """

    run_id: str
    name: str
    parent_id: str | None
    start_time: datetime
    end_time: datetime | None
    attributes: Mapping[str, object]
    error: str | None = None
    trace_id: str | None = None


def infer_event_kind(name: str) -> TraceEventKind:
    """This function infers the normalized event kind from a canonical span name."""
    for prefix, kind in _KIND_PREFIXES:
        if name.startswith(prefix):
            return kind
    return TraceEventKind.STEP


def _fail(message: str) -> NoReturn:
    raise UnsupportedTrace(message=message)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_ATTRIBUTE_PARTS)


def _allowlisted_attributes(
    attributes: Mapping[str, object],
    *,
    run_id: str,
    dropped_keys: list[str],
) -> dict[str, Scalar]:
    """This function keeps allowlisted scalars and classifies every other key.

    Unknown sensitive keys raise a useful error.
    Unknown ordinary keys and non-scalar values are recorded as dropped.
    """
    clean: dict[str, Scalar] = {}
    for key, value in attributes.items():
        if key in TRACE_ATTRIBUTE_ALLOWLIST:
            if isinstance(value, (bool, int, float, str)) and value != "":
                clean[key] = value
            else:
                dropped_keys.append(key)
            continue
        if _is_sensitive_key(key):
            _fail(f"run {run_id!r} records unknown sensitive field {key!r}")
        dropped_keys.append(key)
    return clean


def _sanitize_error(error: str | None, *, dropped_keys: list[str]) -> str | None:
    """This function keeps only stable reason codes from error text."""
    if error is None:
        return None
    if not _STABLE_ERROR_CODE.fullmatch(error):
        dropped_keys.append("error")
        return None
    return error


def _duration_ms(start_time: datetime, end_time: datetime | None) -> float | None:
    if end_time is None:
        return None
    return round((end_time - start_time).total_seconds() * 1000, 2)


def _root_event(events: list[TraceEvent]) -> TraceEvent:
    roots = [event for event in events if event.parent_id is None]
    if len(roots) != 1:
        _fail(f"expected exactly one root run, found {len(roots)}")
    return roots[0]


def _aggregate_tokens(events: list[TraceEvent], root: TraceEvent) -> TokenUsage:
    model_events = [
        event
        for event in events
        if event.kind in (TraceEventKind.ROUTING, TraceEventKind.ANSWER, TraceEventKind.MODEL)
    ]
    if model_events:
        return TokenUsage(
            input_tokens=sum(
                int(event.attributes["model.tokens.input"])
                for event in model_events
                if "model.tokens.input" in event.attributes
            ),
            output_tokens=sum(
                int(event.attributes["model.tokens.output"])
                for event in model_events
                if "model.tokens.output" in event.attributes
            ),
            total_tokens=sum(
                int(event.attributes["model.tokens.total"])
                for event in model_events
                if "model.tokens.total" in event.attributes
            ),
            cost_usd=(
                round(
                    sum(
                        float(event.attributes["model.cost.usd"])
                        for event in model_events
                        if "model.cost.usd" in event.attributes
                    ),
                    6,
                )
                if any("model.cost.usd" in event.attributes for event in model_events)
                else None
            ),
        )
    return TokenUsage(
        input_tokens=int(root.attributes.get("support.tokens.input", 0)),
        output_tokens=int(root.attributes.get("support.tokens.output", 0)),
        total_tokens=int(root.attributes.get("support.tokens.total", 0)),
        cost_usd=(
            float(root.attributes["support.cost.usd"])
            if "support.cost.usd" in root.attributes
            else None
        ),
    )


def _aggregate_timing(events: list[TraceEvent], root: TraceEvent) -> TurnTiming:
    def sum_attribute(name: str) -> float | None:
        values = [event.attributes[name] for event in events if name in event.attributes]
        if not values:
            return None
        return round(sum(float(value) for value in values), 2)

    return TurnTiming(
        total_latency_ms=(
            root.duration_ms
            if root.duration_ms is not None
            else (
                float(root.attributes["support.latency.ms"])
                if "support.latency.ms" in root.attributes
                else None
            )
        ),
        model_latency_ms=sum_attribute("model.latency.ms"),
        db_latency_ms=sum_attribute("db.latency.ms"),
        retrieval_latency_ms=sum_attribute("retrieval.latency.ms"),
    )


def _dependency_calls(events: list[TraceEvent]) -> list[DependencyCall]:
    calls: list[DependencyCall] = []
    for event in events:
        if event.kind not in (
            TraceEventKind.TOOL,
            TraceEventKind.DATABASE,
            TraceEventKind.RETRIEVAL,
        ):
            continue
        error_code = event.error_code
        if error_code is None:
            raw = event.attributes.get("tool.error.code")
            if raw is None:
                raw = event.attributes.get("db.error.code")
            error_code = str(raw) if isinstance(raw, str) else None
        calls.append(
            DependencyCall(
                kind=event.kind,
                name=event.name,
                error_code=error_code,
                duration_ms=event.duration_ms,
            )
        )
    return calls


def normalize_runs(
    runs: Sequence[SourceRun],
    *,
    platform: str,
    project: str | None,
    scenario_id: str | None = None,
    source_url: str | None = None,
    budget_ms: int | None = None,
) -> TraceEvidence:
    """This function converts provider-neutral run nodes into validated evidence.

    The function rejects broken trees with useful errors.
    The function drops unneeded vendor keys and rejects sensitive unknown fields.
    """
    if not runs:
        _fail("the source returned no runs for this trace")
    by_id: dict[str, SourceRun] = {}
    for run in runs:
        if run.run_id in by_id:
            _fail(f"duplicate run id {run.run_id!r}")
        by_id[run.run_id] = run
    roots = [run for run in runs if run.parent_id is None]
    if len(roots) != 1:
        _fail(f"expected exactly one root run, found {len(roots)}")
    for run in runs:
        if run.parent_id is not None and run.parent_id not in by_id:
            _fail(f"run {run.run_id!r} references unknown parent {run.parent_id!r}")

    dropped_keys: list[str] = []
    events: list[TraceEvent] = []
    for run in runs:
        attributes = _allowlisted_attributes(
            run.attributes, run_id=run.run_id, dropped_keys=dropped_keys
        )
        events.append(
            TraceEvent(
                event_id=run.run_id,
                kind=infer_event_kind(run.name),
                name=run.name,
                parent_id=run.parent_id,
                start_time=run.start_time,
                end_time=run.end_time,
                duration_ms=_duration_ms(run.start_time, run.end_time),
                error_code=_sanitize_error(run.error, dropped_keys=dropped_keys),
                attributes=attributes,
            )
        )

    try:
        evidence = _build_evidence(
            events=events,
            runs=runs,
            root=roots[0],
            dropped_keys=dropped_keys,
            platform=platform,
            project=project,
            scenario_id=scenario_id,
            source_url=source_url,
            budget_ms=budget_ms,
        )
    except (InvalidEvidence, UnsupportedTrace):
        raise
    except Exception as error:
        raise InvalidEvidence(message=str(error)) from error
    return evidence


def _build_evidence(
    *,
    events: list[TraceEvent],
    runs: Sequence[SourceRun],
    root: SourceRun,
    dropped_keys: list[str],
    platform: str,
    project: str | None,
    scenario_id: str | None,
    source_url: str | None,
    budget_ms: int | None,
) -> TraceEvidence:
    root_event = _root_event(events)
    outcome_value = root_event.attributes.get("support.outcome")
    reason_code = root_event.attributes.get("support.reason.code")
    if outcome_value is None or not isinstance(outcome_value, str):
        _fail("the selected trace does not record a task outcome (support.outcome)")
    if reason_code is None or not isinstance(reason_code, str):
        _fail("the selected trace does not record a reason code (support.reason.code)")
    try:
        outcome = TraceOutcome(outcome_value)
    except ValueError:
        _fail(f"unknown task outcome {outcome_value!r}")

    source = TraceSourceRef(
        platform=platform,
        project=project,
        trace_id=runs[0].trace_id or runs[0].run_id,
        run_id=root.run_id,
        url=source_url,
    )
    model = TraceModelRef(
        provider=(
            str(root_event.attributes["agent.model.provider"])
            if isinstance(root_event.attributes.get("agent.model.provider"), str)
            else None
        ),
        name=(
            str(root_event.attributes["agent.model.name"])
            if isinstance(root_event.attributes.get("agent.model.name"), str)
            else None
        ),
    )
    task_input = {
        key: root_event.attributes[key]
        for key in TASK_INPUT_ALLOWLIST
        if key in root_event.attributes
    }
    task_output = {
        key: root_event.attributes[key]
        for key in TASK_OUTPUT_ALLOWLIST
        if key in root_event.attributes
    }
    if "support.retry.count" in root_event.attributes:
        retry_count = int(root_event.attributes["support.retry.count"])
    else:
        retry_count = sum(1 for event in events if event.kind is TraceEventKind.RETRY)

    policy_decisions = [
        PolicyDecision(
            version=(
                str(event.attributes["policy.version"])
                if isinstance(event.attributes.get("policy.version"), str)
                else None
            ),
            decision=(
                str(event.attributes["policy.decision"])
                if isinstance(event.attributes.get("policy.decision"), str)
                else None
            ),
            reason_code=(
                str(event.attributes["policy.reason.code"])
                if isinstance(event.attributes.get("policy.reason.code"), str)
                else None
            ),
        )
        for event in events
        if event.kind is TraceEventKind.POLICY
    ]
    confirmation: ConfirmationDecision | None = None
    for event in events:
        if event.kind is TraceEventKind.CONFIRMATION:
            confirmation = ConfirmationDecision(
                required=bool(event.attributes.get("confirmation.required", True)),
                verified=bool(event.attributes.get("confirmation.verified", False)),
            )
            break

    timing = _aggregate_timing(events, root_event)
    return TraceEvidence(
        evidence_id=stable_evidence_id(source),
        source=source,
        scenario_id=scenario_id,
        workflow=root.name.split(".", maxsplit=1)[0],
        environment=(
            str(root_event.attributes["service.environment"])
            if isinstance(root_event.attributes.get("service.environment"), str)
            else None
        ),
        workflow_version=(
            str(root_event.attributes["agent.workflow.version"])
            if isinstance(root_event.attributes.get("agent.workflow.version"), str)
            else None
        ),
        model=model,
        outcome=outcome,
        reason_code=reason_code,
        events=events,
        task_input=task_input,
        task_output=task_output,
        tokens=_aggregate_tokens(events, root_event),
        timing=timing.model_copy(update={"budget_ms": budget_ms}),
        retry_count=retry_count,
        dependency_calls=_dependency_calls(events),
        policy_decisions=policy_decisions,
        confirmation=confirmation,
        redaction=RedactionMetadata(dropped_keys=tuple(dict.fromkeys(dropped_keys))),
    )
