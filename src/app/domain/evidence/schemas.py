"""This module defines the vendor-neutral TraceEvidence schema.

TraceEvidence represents one selected production run after normalization.
Every artifact stores source identifiers, schema versions, and content hashes.
The schema rejects broken event order, invalid parent references, and unknown
fields. Event attributes must come from the trace attribute allowlist.
"""

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.telemetry.allowlist import TRACE_ATTRIBUTE_ALLOWLIST

TRACE_EVIDENCE_SCHEMA_VERSION = "3.0.0"

Scalar = bool | int | float | str

TASK_INPUT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "agent.workflow.version",
        "agent.routing.instructions.version",
        "agent.answer.instructions.version",
        "support.intent",
        "support.confidence",
        "support.message.length",
    }
)

TASK_OUTPUT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "support.outcome",
        "support.reason.code",
        "support.policy.grounded",
        "support.retry.count",
    }
)


class TraceEventKind(StrEnum):
    """This enum defines the normalized kind for one event in a trace."""

    TURN = "turn"
    ROUTING = "routing"
    ANSWER = "answer"
    MODEL = "model"
    TOOL = "tool"
    RETRIEVAL = "retrieval"
    DATABASE = "database"
    POLICY = "policy"
    CONFIRMATION = "confirmation"
    ESCALATION = "escalation"
    RETRY = "retry"
    STEP = "step"


class TraceOutcome(StrEnum):
    """This enum defines the stable task outcome values for evidence."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    FAILED = "failed"


class TraceEvent(BaseModel):
    """This class stores one ordered event from the selected trace."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    kind: TraceEventKind
    name: str = Field(min_length=1, max_length=200)
    parent_id: str | None = Field(default=None, max_length=200)
    start_time: datetime
    end_time: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    attributes: dict[str, Scalar] = Field(default_factory=dict)


class TraceSourceRef(BaseModel):
    """This class stores the provenance of one piece of evidence."""

    model_config = ConfigDict(extra="forbid")

    platform: str = Field(min_length=1, max_length=50)
    project: str | None = Field(default=None, max_length=200)
    trace_id: str = Field(min_length=1, max_length=200)
    run_id: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)


class TraceModelRef(BaseModel):
    """This class stores the model configuration recorded for one trace."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=200)


class TokenUsage(BaseModel):
    """This class stores aggregated token and cost data for one trace."""

    model_config = ConfigDict(extra="forbid")

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)


class TurnTiming(BaseModel):
    """This class stores timing data for one trace and its dependencies."""

    model_config = ConfigDict(extra="forbid")

    total_latency_ms: float | None = Field(default=None, ge=0)
    model_latency_ms: float | None = Field(default=None, ge=0)
    db_latency_ms: float | None = Field(default=None, ge=0)
    retrieval_latency_ms: float | None = Field(default=None, ge=0)
    budget_ms: int | None = Field(default=None, ge=1)


class DependencyCall(BaseModel):
    """This class stores one tool, database, or retrieval call from a trace."""

    model_config = ConfigDict(extra="forbid")

    kind: TraceEventKind
    name: str = Field(min_length=1, max_length=200)
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    duration_ms: float | None = Field(default=None, ge=0)


class PolicyDecision(BaseModel):
    """This class stores one recorded policy decision from a trace."""

    model_config = ConfigDict(extra="forbid")

    version: str | None = Field(default=None, max_length=100)
    decision: str | None = Field(default=None, max_length=100)
    reason_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")


class ConfirmationDecision(BaseModel):
    """This class stores the confirmation outcome recorded for a trace."""

    model_config = ConfigDict(extra="forbid")

    required: bool
    verified: bool


class RedactionMetadata(BaseModel):
    """This class records what the mapping removed and why."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(
        default=(
            "Only allowlisted attributes are kept. Unknown sensitive fields "
            "are rejected. Unneeded vendor keys are dropped."
        ),
        max_length=500,
    )
    dropped_keys: tuple[str, ...] = ()


class TraceEvidence(BaseModel):
    """This class stores one normalized selected trace.

    The schema is vendor-neutral: any source adapter produces this shape.
    The importer stores the evidence with its content hash and import version.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=TRACE_EVIDENCE_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    evidence_id: UUID
    source: TraceSourceRef
    scenario_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]*$")
    workflow: str | None = Field(default=None, max_length=100)
    environment: str | None = Field(default=None, max_length=100)
    workflow_version: str | None = Field(default=None, max_length=50)
    model: TraceModelRef | None = None
    outcome: TraceOutcome
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    events: list[TraceEvent] = Field(min_length=1)
    task_input: dict[str, Scalar] = Field(default_factory=dict)
    task_output: dict[str, Scalar] = Field(default_factory=dict)
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    timing: TurnTiming = Field(default_factory=TurnTiming)
    retry_count: int = Field(default=0, ge=0)
    dependency_calls: list[DependencyCall] = Field(default_factory=list)
    policy_decisions: list[PolicyDecision] = Field(default_factory=list)
    confirmation: ConfirmationDecision | None = None
    redaction: RedactionMetadata = Field(default_factory=RedactionMetadata)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_event_tree(self) -> "TraceEvidence":
        """This method rejects broken event order and invalid parent references."""
        for field_name, values, allowlist in (
            ("task_input", self.task_input, TASK_INPUT_ALLOWLIST),
            ("task_output", self.task_output, TASK_OUTPUT_ALLOWLIST),
        ):
            unknown = sorted(set(values) - allowlist)
            if unknown:
                raise ValueError(f"{field_name} records non-allowlisted fields {unknown!r}")

        seen: dict[str, int] = {}
        roots = 0
        for index, event in enumerate(self.events):
            if event.event_id in seen:
                raise ValueError(f"duplicate event id {event.event_id!r}")
            seen[event.event_id] = index
            if event.end_time is not None and event.end_time < event.start_time:
                raise ValueError(f"event {event.event_id!r} ends before it starts")
            for key in event.attributes:
                if key not in TRACE_ATTRIBUTE_ALLOWLIST:
                    raise ValueError(
                        f"event {event.event_id!r} records non-allowlisted attribute {key!r}"
                    )
            if event.parent_id is None:
                roots += 1
                continue
            parent_index = seen.get(event.parent_id)
            if parent_index is None:
                raise ValueError(
                    f"event {event.event_id!r} references unknown parent {event.parent_id!r}"
                )
            parent = self.events[parent_index]
            if event.start_time < parent.start_time:
                raise ValueError(
                    f"event {event.event_id!r} starts before its parent {event.parent_id!r}"
                )
        if roots != 1:
            raise ValueError(f"a trace must have exactly one root event, found {roots}")
        return self


class EvidenceSummary(BaseModel):
    """This class stores the core facts that downstream code reads from evidence.

    Downstream measurement code receives this shape from every provider.
    """

    model_config = ConfigDict(extra="forbid")

    platform: str
    trace_id: str
    scenario_id: str | None
    outcome: TraceOutcome
    reason_code: str
    model_name: str | None
    workflow_version: str | None
    total_latency_ms: float | None
    tokens_total: int
    cost_usd: float | None
    retry_count: int
    tool_names: tuple[str, ...]
    policy_decision_count: int
    confirmation_verified: bool | None


def summarize_evidence(evidence: TraceEvidence) -> EvidenceSummary:
    """This function reduces one trace to the core contract for measurement code."""
    return EvidenceSummary(
        platform=evidence.source.platform,
        trace_id=evidence.source.trace_id,
        scenario_id=evidence.scenario_id,
        outcome=evidence.outcome,
        reason_code=evidence.reason_code,
        model_name=evidence.model.name if evidence.model is not None else None,
        workflow_version=evidence.workflow_version,
        total_latency_ms=evidence.timing.total_latency_ms,
        tokens_total=evidence.tokens.total_tokens,
        cost_usd=evidence.tokens.cost_usd,
        retry_count=evidence.retry_count,
        tool_names=tuple(
            sorted(
                {
                    call.name
                    for call in evidence.dependency_calls
                    if call.kind is TraceEventKind.TOOL
                }
            )
        ),
        policy_decision_count=len(evidence.policy_decisions),
        confirmation_verified=(
            evidence.confirmation.verified if evidence.confirmation is not None else None
        ),
    )


def compute_content_hash(evidence: TraceEvidence) -> str:
    """This function returns a stable hash for one piece of evidence.

    The hash excludes the stored hash itself. Any content change changes the hash.
    """
    canonical = json.dumps(
        evidence.model_dump(mode="json", exclude={"content_hash"}),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()
