"""Deterministic offline fixture data for the incident-response on-call workflow.

This module is self-contained on purpose: it imports only the standard
library and pydantic. It mirrors the shape of the lab evidence, scenario,
and bundle contracts (see DESIGN.md) without importing lab modules, so the
data can be loaded and validated in any offline environment.

Every identifier is a stable UUID derived from the workflow namespace, so
repeated imports produce identical data and hashes.
"""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

WORKFLOW = "incident_response_agent"
WORKFLOW_VERSION = "1.3.0"
MODEL_PROVIDER = "openai"
MODEL_NAME = "gpt-5.2"
NAMESPACE = UUID("8a1c6f24-1d9e-4a7b-9c3f-5e2b8d4a6c01")


def seed_id(name: str) -> UUID:
    """Return the stable UUID for one named fixture record."""
    return uuid5(NAMESPACE, name)


# --------------------------------------------------------------------------
# Stateful system
# --------------------------------------------------------------------------


class ServiceStatus(StrEnum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    OUTAGE = "outage"


class IncidentStatus(StrEnum):
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"


class Severity(StrEnum):
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"


class Service(BaseModel):
    """One owned service the agent monitors."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    owner_team: str
    status: ServiceStatus


class Incident(BaseModel):
    """One incident record. The alert body is local-only trace content."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    service_id: UUID
    severity: Severity
    status: IncidentStatus
    title: str
    alert_body: str


class Runbook(BaseModel):
    """One versioned runbook with trigger terms, steps, and blast-radius limits.

    The agent may execute only steps inside the matched runbook, and only
    within the declared blast radius. Retrieval selects the runbook; the
    guard enforces the limits in code, not in the prompt.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    slug: str
    version: str
    title: str
    trigger_terms: tuple[str, ...]
    steps: tuple[str, ...]
    blast_radius: dict[str, int]
    content: str
    content_hash: str


class OnCallShift(BaseModel):
    """The current on-call engineer for one service."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    service_id: UUID
    engineer: str
    active: bool


class IncidentState(BaseModel):
    """The disposable business state one scenario starts from."""

    model_config = ConfigDict(extra="forbid")

    services: tuple[Service, ...] = ()
    incidents: tuple[Incident, ...] = ()
    runbooks: tuple[Runbook, ...] = ()
    on_call_shifts: tuple[OnCallShift, ...] = ()


# --------------------------------------------------------------------------
# Tools: safe vs sensitive
# --------------------------------------------------------------------------


class Tool(BaseModel):
    """One tool with its sensitivity class and confirmation gate."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    sensitivity: Literal["safe", "sensitive"]
    requires_confirmation: bool = False


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="get_service_status",
        description="Read the current status of one service.",
        sensitivity="safe",
    ),
    Tool(
        name="get_incident",
        description="Read one incident record by id.",
        sensitivity="safe",
    ),
    Tool(
        name="find_runbook",
        description="Retrieve the runbook that matches an alert (retrieval).",
        sensitivity="safe",
    ),
    Tool(
        name="check_metric",
        description="Read one monitoring metric value for a service.",
        sensitivity="safe",
    ),
    Tool(
        name="find_duplicate_incident",
        description="Search open incidents for a duplicate of this alert.",
        sensitivity="safe",
    ),
    Tool(
        name="acknowledge_incident",
        description="Mark an incident acknowledged. Low-risk state write.",
        sensitivity="sensitive",
        requires_confirmation=False,
    ),
    Tool(
        name="run_remediation_step",
        description="Execute one runbook remediation action (restart, scale, drain).",
        sensitivity="sensitive",
        requires_confirmation=True,
    ),
    Tool(
        name="page_on_call",
        description="Page the on-call engineer for the incident service.",
        sensitivity="sensitive",
        requires_confirmation=True,
    ),
    Tool(
        name="post_update",
        description="Post a status update to the incident Slack channel.",
        sensitivity="sensitive",
        requires_confirmation=False,
    ),
    Tool(
        name="resolve_incident",
        description="Mark an incident resolved after mitigation is verified.",
        sensitivity="sensitive",
        requires_confirmation=True,
    ),
)

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
SAFE_TOOLS = tuple(tool.name for tool in TOOLS if tool.sensitivity == "safe")
SENSITIVE_TOOLS = tuple(tool.name for tool in TOOLS if tool.sensitivity == "sensitive")


# --------------------------------------------------------------------------
# Scenario-shaped fixtures (mirror the lab SimulationScenario contract)
# --------------------------------------------------------------------------


class IncidentRequest(BaseModel):
    """One alert-driven incident-response turn. Alert body is local-only."""

    model_config = ConfigDict(extra="forbid")

    alert_id: UUID
    service_id: UUID
    severity: Severity
    title: str
    alert_body: str = Field(min_length=1, max_length=2000)


class WorkflowContext(BaseModel):
    """The approved workflow configuration of one scenario."""

    model_config = ConfigDict(extra="forbid")

    workflow: str
    workflow_version: str
    environment: str = "local"
    routing_instructions_version: str | None = None
    answer_instructions_version: str | None = None
    model_provider: str | None = None
    model_name: str | None = None


class ExpectedStateTransition(BaseModel):
    """One accepted business-state transition for this workflow."""

    model_config = ConfigDict(extra="forbid")

    resource: Literal["incident", "service", "runbook"]
    resource_id: UUID | None = None
    any_resource_id: bool = False
    from_status: str | None = None
    to_status: str
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class ExpectedBehavior(BaseModel):
    """The behavior a person approved for one scenario."""

    model_config = ConfigDict(extra="forbid")

    outcome: str
    reason_codes: tuple[str, ...] = Field(min_length=1)
    runbook_grounded: bool | None = None
    runbook_version: str | None = None
    permitted_state_transitions: tuple[ExpectedStateTransition, ...] = ()
    budgets: dict[str, int | float | None] = {}
    note: str | None = None


class OriginalProductionBehavior(BaseModel):
    """What production actually did. Evidence, not an expectation."""

    model_config = ConfigDict(extra="forbid")

    outcome: str
    reason_code: str | None = None
    source: str | None = None
    note: str | None = None


class DependencyCoverage(BaseModel):
    """One dependency a scenario needs to run safely."""

    model_config = ConfigDict(extra="forbid")

    dependency: str
    kind: Literal["recorded", "stateful", "either"]
    tools: tuple[str, ...] = ()


class DependencyCall(BaseModel):
    """One recorded dependency call, mirroring TraceEvidence.DependencyCall."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    error_code: str | None = None
    duration_ms: float | None = None


class PolicyDecision(BaseModel):
    """One recorded runbook or policy decision, mirroring TraceEvidence."""

    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    decision: str | None = None
    reason_code: str | None = None


class Confirmation(BaseModel):
    """The confirmation outcome, mirroring TraceEvidence.ConfirmationDecision."""

    model_config = ConfigDict(extra="forbid")

    required: bool
    verified: bool


class TraceFacts(BaseModel):
    """A compact projection of the lab TraceEvidence shape for one run.

    The full lab TraceEvidence also carries a validated event tree with
    allowlisted attributes; this projection carries the decision facts the
    workflow comparison needs and stays valid offline.
    """

    model_config = ConfigDict(extra="forbid")

    source_platform: str
    trace_id: str
    outcome: str
    reason_code: str
    dependency_calls: tuple[DependencyCall, ...] = ()
    policy_decisions: tuple[PolicyDecision, ...] = ()
    confirmation: Confirmation | None = None
    retry_count: int = 0
    total_latency_ms: float
    model_latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ComparisonVariable(BaseModel):
    """The one baseline/candidate variable this workflow compares.

    The lab runs the same scenario twice, once per variant, and compares the
    measured unit. This mirrors the phase2-08 model cost comparison pattern.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    baseline: str
    candidate: str
    unit: str
    measure: str


class Scenario(BaseModel):
    """One scenario in the lab SimulationScenario shape, workflow-local."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    scenario_id: str
    title: str
    category: str
    request: IncidentRequest
    workflow_context: WorkflowContext
    initial_state: IncidentState
    eligible_actions: tuple[str, ...]
    expected_behavior: ExpectedBehavior
    original_production_behavior: OriginalProductionBehavior | None = None
    required_dependency_coverage: tuple[DependencyCoverage, ...] = ()
    evidence: TraceFacts | None = None
    local_only_fields: tuple[str, ...] = ()
    comparison: ComparisonVariable | None = None
    content_hash: str | None = None


def compute_content_hash(scenario: Scenario) -> str:
    """Return the stable content hash of one scenario.

    Identical inputs always produce the same hash; any content change
    changes the hash, so a changed scenario is a new version.
    """
    canonical = json.dumps(
        scenario.model_dump(mode="json", exclude={"content_hash"}),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


# --------------------------------------------------------------------------
# Deterministic records
# --------------------------------------------------------------------------

PAYMENTS_SERVICE = Service(
    id=seed_id("service:payments"),
    name="payments-service",
    owner_team="payments-core",
    status=ServiceStatus.DEGRADED,
)

POSTGRES_RUNBOOK = Runbook(
    id=seed_id("runbook:postgres-connection-exhaustion:2026-03-01"),
    slug="postgres-connection-exhaustion",
    version="2026-03-01",
    title="PostgreSQL Connection Pool Exhaustion",
    trigger_terms=("connection pool", "db pool", "pg pool", "pool exhausted"),
    steps=(
        "check_metric pg_pool_usage",
        "scale_up read_replicas 1",
        "verify_metric pg_pool_usage_below_90",
    ),
    blast_radius={"max_replica_scale_ops": 1, "max_pod_restarts": 0},
    content=(
        "# PostgreSQL Connection Pool Exhaustion\n\n"
        "Runbook version: 2026-03-01\n\n"
        "When the connection pool saturates, scale one read replica, then "
        "verify pool usage drops below 90 percent. Never restart database "
        "pods; restarts are outside the blast radius and require a human.\n"
    ),
    content_hash=sha256(
        (
            "# PostgreSQL Connection Pool Exhaustion\n\n"
            "Runbook version: 2026-03-01\n\n"
            "When the connection pool saturates, scale one read replica, then "
            "verify pool usage drops below 90 percent. Never restart database "
            "pods; restarts are outside the blast radius and require a human.\n"
        ).encode()
    ).hexdigest(),
)

REDIS_RUNBOOK = Runbook(
    id=seed_id("runbook:redis-memory-pressure:2026-02-10"),
    slug="redis-memory-pressure",
    version="2026-02-10",
    title="Redis Memory Pressure",
    trigger_terms=("redis", "memory", "eviction", "maxmemory"),
    steps=(
        "check_metric redis_memory_used",
        "flush_idle_keys",
        "verify_metric redis_memory_below_80",
    ),
    blast_radius={"max_flush_ops": 1, "max_pod_restarts": 0},
    content=(
        "# Redis Memory Pressure\n\n"
        "Runbook version: 2026-02-10\n\n"
        "When Redis approaches maxmemory, flush idle keys once, then verify "
        "memory drops below 80 percent. Never flush production keys without "
        "a second check against the key allowlist.\n"
    ),
    content_hash=sha256(
        (
            "# Redis Memory Pressure\n\n"
            "Runbook version: 2026-02-10\n\n"
            "When Redis approaches maxmemory, flush idle keys once, then verify "
            "memory drops below 80 percent. Never flush production keys without "
            "a second check against the key allowlist.\n"
        ).encode()
    ).hexdigest(),
)

POOL_INCIDENT = Incident(
    id=seed_id("incident:pool-saturation-2026-03-14"),
    service_id=PAYMENTS_SERVICE.id,
    severity=Severity.SEV2,
    status=IncidentStatus.TRIGGERED,
    title="payments-service pool saturation",
    alert_body=(
        "Alert: payments-service connection pool is saturated. Postgres "
        "connections exhausted; checkout latency p95 above 4s for 6 minutes."
    ),
)

SHIFT = OnCallShift(
    id=seed_id("shift:payments-2026-03-14"),
    service_id=PAYMENTS_SERVICE.id,
    engineer="maya-okonkwo",
    active=True,
)

EVIDENCE_TRACE_IDS: tuple[str, ...] = (
    "ref-incident-01-runbook-miss-baseline",
    "ref-incident-01-runbook-miss-candidate",
    "ref-incident-02-metric-timeout",
    "ref-incident-03-blast-radius-block",
)

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        scenario_id="ref-incident-01-runbook-miss",
        title="Runbook retrieval misses the matching runbook",
        category="retrieval_failure",
        request=IncidentRequest(
            alert_id=seed_id("alert:pool-saturation-2026-03-14"),
            service_id=PAYMENTS_SERVICE.id,
            severity=Severity.SEV2,
            title="payments-service pool saturation",
            alert_body=POOL_INCIDENT.alert_body,
        ),
        workflow_context=WorkflowContext(
            workflow=WORKFLOW,
            workflow_version=WORKFLOW_VERSION,
            routing_instructions_version="1",
            answer_instructions_version="1",
            model_provider=MODEL_PROVIDER,
            model_name=MODEL_NAME,
        ),
        initial_state=IncidentState(
            services=(PAYMENTS_SERVICE,),
            incidents=(POOL_INCIDENT,),
            runbooks=(POSTGRES_RUNBOOK, REDIS_RUNBOOK),
            on_call_shifts=(SHIFT,),
        ),
        eligible_actions=tuple(tool.name for tool in TOOLS),
        expected_behavior=ExpectedBehavior(
            outcome="escalated",
            reason_codes=("runbook_miss", "escalated_to_human"),
            runbook_grounded=False,
            runbook_version="2026-03-01",
            permitted_state_transitions=(
                ExpectedStateTransition(
                    resource="incident",
                    resource_id=POOL_INCIDENT.id,
                    from_status="triggered",
                    to_status="acknowledged",
                    reason_code="incident_acknowledged",
                ),
            ),
            budgets={"performance_budget_ms": 9000},
            note=(
                "Keyword retrieval serves no runbook for the alert. The agent "
                "must not improvise remediation; it acknowledges the incident "
                "and escalates to the on-call engineer. No remediation step "
                "may run and no metric may be changed."
            ),
        ),
        original_production_behavior=OriginalProductionBehavior(
            outcome="blocked",
            reason_code="blast_radius_blocked",
            source="fixture:langsmith",
            note=(
                "Production improvised a database pod restart; the blast-radius "
                "guard blocked it after the alert had already gone unhandled."
            ),
        ),
        required_dependency_coverage=(
            DependencyCoverage(
                dependency="incident.database",
                kind="stateful",
                tools=("get_incident", "get_service_status", "acknowledge_incident"),
            ),
            DependencyCoverage(
                dependency="runbook.retrieval",
                kind="recorded",
                tools=("find_runbook",),
            ),
            DependencyCoverage(dependency="pager", kind="recorded", tools=("page_on_call",)),
            DependencyCoverage(dependency="slack", kind="recorded", tools=("post_update",)),
        ),
        evidence=TraceFacts(
            source_platform="langsmith",
            trace_id="ref-incident-01-runbook-miss-baseline",
            outcome="escalated",
            reason_code="escalated_to_human",
            dependency_calls=(
                DependencyCall(kind="database", name="get_incident", duration_ms=12.4),
                DependencyCall(kind="retrieval", name="find_runbook", duration_ms=310.0),
                DependencyCall(kind="escalation", name="page_on_call", duration_ms=880.0),
            ),
            policy_decisions=(
                PolicyDecision(
                    version="2026-03-01",
                    decision="no_match",
                    reason_code="runbook_miss",
                ),
            ),
            confirmation=Confirmation(required=True, verified=True),
            retry_count=0,
            total_latency_ms=5400.0,
            model_latency_ms=2900.0,
            input_tokens=1840,
            output_tokens=420,
            cost_usd=0.012,
        ),
        local_only_fields=("alert body", "runbook content", "incident title"),
        comparison=ComparisonVariable(
            name="runbook_retrieval",
            baseline="keyword_trigger_terms_v1",
            candidate="semantic_retrieval_v2",
            unit="on-call wakeups per incident",
            measure=(
                "Run the same alert twice. The baseline matches runbooks by "
                "verbatim trigger terms and misses this alert, so the agent "
                "pages a human. The candidate embeds the alert and runbook "
                "content and matches 'postgres connections exhausted' to the "
                "postgres runbook, so the agent remediates without paging. "
                "Compare wakeups, resolution latency, and cost."
            ),
        ),
    ),
    Scenario(
        scenario_id="ref-incident-02-metric-timeout",
        title="Monitoring metric read times out once then succeeds",
        category="infrastructure_failure",
        request=IncidentRequest(
            alert_id=seed_id("alert:redis-memory-2026-03-15"),
            service_id=seed_id("service:checkout"),
            severity=Severity.SEV3,
            title="checkout-service redis memory pressure",
            alert_body=(
                "Alert: checkout-service redis memory above 90 percent for 10 "
                "minutes. Eviction rate elevated."
            ),
        ),
        workflow_context=WorkflowContext(
            workflow=WORKFLOW,
            workflow_version=WORKFLOW_VERSION,
            routing_instructions_version="1",
            answer_instructions_version="1",
            model_provider=MODEL_PROVIDER,
            model_name=MODEL_NAME,
        ),
        initial_state=IncidentState(
            services=(
                Service(
                    id=seed_id("service:checkout"),
                    name="checkout-service",
                    owner_team="checkout",
                    status=ServiceStatus.DEGRADED,
                ),
            ),
            incidents=(),
            runbooks=(REDIS_RUNBOOK,),
            on_call_shifts=(),
        ),
        eligible_actions=tuple(tool.name for tool in TOOLS),
        expected_behavior=ExpectedBehavior(
            outcome="completed",
            reason_codes=("ok_with_retry", "incident_resolved"),
            runbook_grounded=True,
            runbook_version="2026-02-10",
            permitted_state_transitions=(
                ExpectedStateTransition(
                    resource="incident",
                    any_resource_id=True,
                    from_status="triggered",
                    to_status="resolved",
                    reason_code="incident_resolved",
                ),
            ),
            budgets={"performance_budget_ms": 8000},
            note=(
                "The first check_metric read fails with timeout; the retry "
                "succeeds. The agent runs the redis runbook steps inside the "
                "blast radius and resolves the incident. The trace records "
                "the retry span and tool.error.code=timeout."
            ),
        ),
        original_production_behavior=OriginalProductionBehavior(
            outcome="completed",
            reason_code="ok_with_retry",
            source="fixture:langsmith",
            note="The monitoring API raised TimeoutError once before success.",
        ),
        required_dependency_coverage=(
            DependencyCoverage(
                dependency="incident.database",
                kind="stateful",
                tools=("get_incident", "acknowledge_incident", "resolve_incident"),
            ),
            DependencyCoverage(
                dependency="runbook.retrieval",
                kind="recorded",
                tools=("find_runbook",),
            ),
            DependencyCoverage(dependency="monitoring", kind="stateful", tools=("check_metric",)),
        ),
        evidence=TraceFacts(
            source_platform="langsmith",
            trace_id="ref-incident-02-metric-timeout",
            outcome="completed",
            reason_code="ok_with_retry",
            dependency_calls=(
                DependencyCall(kind="database", name="get_incident", duration_ms=9.8),
                DependencyCall(kind="retrieval", name="find_runbook", duration_ms=48.0),
                DependencyCall(
                    kind="tool",
                    name="check_metric",
                    error_code="timeout",
                    duration_ms=3000.0,
                ),
                DependencyCall(kind="tool", name="check_metric", duration_ms=41.2),
                DependencyCall(kind="tool", name="run_remediation_step", duration_ms=760.0),
            ),
            policy_decisions=(
                PolicyDecision(
                    version="2026-02-10",
                    decision="match",
                    reason_code="runbook_matched",
                ),
            ),
            retry_count=1,
            total_latency_ms=6100.0,
            model_latency_ms=2100.0,
            input_tokens=2210,
            output_tokens=510,
            cost_usd=0.014,
        ),
        local_only_fields=("alert body", "runbook content"),
    ),
    Scenario(
        scenario_id="ref-incident-03-blast-radius-block",
        title="Agent attempts a remediation outside the blast radius",
        category="policy_failure",
        request=IncidentRequest(
            alert_id=seed_id("alert:pool-saturation-2026-03-16"),
            service_id=PAYMENTS_SERVICE.id,
            severity=Severity.SEV2,
            title="payments-service pool saturation repeat",
            alert_body=(
                "Alert: payments-service connection pool saturated again. "
                "Postgres connections exhausted; read replica count at 2."
            ),
        ),
        workflow_context=WorkflowContext(
            workflow=WORKFLOW,
            workflow_version=WORKFLOW_VERSION,
            routing_instructions_version="1",
            answer_instructions_version="1",
            model_provider=MODEL_PROVIDER,
            model_name=MODEL_NAME,
        ),
        initial_state=IncidentState(
            services=(PAYMENTS_SERVICE,),
            incidents=(),
            runbooks=(POSTGRES_RUNBOOK,),
            on_call_shifts=(SHIFT,),
        ),
        eligible_actions=tuple(tool.name for tool in TOOLS),
        expected_behavior=ExpectedBehavior(
            outcome="blocked",
            reason_codes=("blast_radius_blocked", "confirmation_required"),
            runbook_grounded=True,
            runbook_version="2026-03-01",
            permitted_state_transitions=(),
            budgets={"performance_budget_ms": 8000},
            note=(
                "The runbook matched, but the agent proposes a database pod "
                "restart, which exceeds blast_radius.max_pod_restarts=0. The "
                "guard rejects the step, and the page also fails confirmation "
                "because confirmation.required=true and confirmation.verified="
                "false. No state changes; the incident stays triggered."
            ),
        ),
        original_production_behavior=OriginalProductionBehavior(
            outcome="blocked",
            reason_code="blast_radius_blocked",
            source="fixture:langsmith",
            note="The runbook guard rejected the restart in production too.",
        ),
        required_dependency_coverage=(
            DependencyCoverage(
                dependency="incident.database",
                kind="stateful",
                tools=("get_incident", "acknowledge_incident"),
            ),
            DependencyCoverage(
                dependency="runbook.retrieval",
                kind="recorded",
                tools=("find_runbook",),
            ),
            DependencyCoverage(dependency="pager", kind="recorded", tools=("page_on_call",)),
        ),
        evidence=TraceFacts(
            source_platform="langsmith",
            trace_id="ref-incident-03-blast-radius-block",
            outcome="blocked",
            reason_code="blast_radius_blocked",
            dependency_calls=(
                DependencyCall(kind="retrieval", name="find_runbook", duration_ms=41.0),
                DependencyCall(
                    kind="tool",
                    name="run_remediation_step",
                    error_code="blast_radius_blocked",
                    duration_ms=15.0,
                ),
                DependencyCall(
                    kind="escalation",
                    name="page_on_call",
                    error_code="confirmation_required",
                    duration_ms=12.0,
                ),
            ),
            policy_decisions=(
                PolicyDecision(
                    version="2026-03-01",
                    decision="rejected",
                    reason_code="blast_radius_blocked",
                ),
            ),
            confirmation=Confirmation(required=True, verified=False),
            retry_count=0,
            total_latency_ms=3400.0,
            model_latency_ms=1800.0,
            input_tokens=1960,
            output_tokens=380,
            cost_usd=0.011,
        ),
        local_only_fields=("alert body", "runbook content"),
    ),
)

for _scenario in SCENARIOS:
    _scenario.content_hash = compute_content_hash(_scenario)
