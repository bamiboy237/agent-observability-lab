"""Deterministic offline fixture data for the HR onboarding coordinator agent.

This module is a self-contained reference fixture for the agent-observability
lab. It mirrors the shape of the customer-support seed data but stays fully
offline: no database, no network, no imports from ``app``. Every identifier is
a stable UUID derived from a fixed namespace, checklist content carries a
sha256 content hash, and every scenario carries a stable content hash computed
from its canonical JSON. The lab can use this data to construct
``SimulationScenario`` and ``SimulationBundle`` records after the domain
mapping described in ``docs/reference_workflows/onboarding-coordinator-agent.md``.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid5

SEED_NAMESPACE = UUID("62b1a42f-3c5d-4e7f-9a0b-2d3e4f5a6b7c")

SCENARIO_ID_PREFIX = "onboarding"
WORKFLOW_SLUG = "onboarding_coordinator_agent"
WORKFLOW_VERSION = "1.0.0"


def seed_id(name: str) -> UUID:
    """Return the stable UUID for one named fixture record."""
    return uuid5(SEED_NAMESPACE, name)


def content_hash(text: str) -> str:
    """Return the sha256 hex digest of one checklist or policy body."""
    return sha256(text.encode()).hexdigest()


class ChecklistPolicyVersion(StrEnum):
    CURRENT = "2026-08-01"
    PREVIOUS = "2026-02-01"


class OnboardingCaseStatus(StrEnum):
    INTAKE = "intake"
    DRAFTING = "drafting"
    AWAITING_REVIEW = "awaiting_review"
    ACTIVE = "active"
    BLOCKED = "blocked"


class WorkerRecordStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"


class OnboardingTaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WAIVED = "waived"


class ScenarioCategory(StrEnum):
    ANSWER_FAILURE = "answer_failure"
    RETRIEVAL_FAILURE = "retrieval_failure"
    POLICY_FAILURE = "policy_failure"
    TOOL_FAILURE = "tool_failure"
    LATENCY_FAILURE = "latency_failure"
    COST_COMPARISON = "cost_comparison"


class ScenarioOutcome(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    FAILED = "failed"


class ReasonCode(StrEnum):
    CHECKLIST_COMPLETED = "checklist_completed"
    COMPLIANCE_TASK_MISSED = "compliance_task_missed"
    WORKER_RECORD_DRAFTED = "worker_record_drafted"
    WORKER_RECORD_ACTIVATED = "worker_record_activated"
    RECORD_ACTIVATION_BLOCKED_UNCONFIRMED = "record_activation_blocked_unconfirmed"
    COMPENSATION_MISMATCH = "compensation_mismatch"
    PAYROLL_NOT_READY = "payroll_not_ready"
    ESCALATED = "escalated"
    MODEL_ERROR = "model_error"
    TOOL_ERROR = "tool_error"


@dataclass(frozen=True)
class OnboardingPolicyDocument:
    """One versioned compliance checklist policy."""

    id: UUID
    slug: str
    version: str
    title: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class Candidate:
    """One hired candidate who is moving through onboarding."""

    id: UUID
    name: str
    email: str
    work_authorization_verified: bool


@dataclass(frozen=True)
class Position:
    """One open position the candidate will fill."""

    id: UUID
    title: str
    department: str
    location: str
    compensation_tier: str


@dataclass(frozen=True)
class WorkerRecord:
    """The system-of-record worker entry the agent drafts or activates."""

    id: UUID
    candidate_id: UUID
    position_id: UUID
    status: WorkerRecordStatus
    compensation_tier: str
    start_date: date


@dataclass(frozen=True)
class ChecklistTemplate:
    """One versioned onboarding checklist template."""

    id: UUID
    slug: str
    version: str
    title: str
    tasks: tuple[str, ...]
    content_hash: str


@dataclass(frozen=True)
class OnboardingTask:
    """One checklist item tracked against a worker record."""

    id: UUID
    worker_record_id: UUID
    template_slug: str
    task_name: str
    status: OnboardingTaskStatus
    required_for_payroll: bool


@dataclass(frozen=True)
class OnboardingCase:
    """One onboarding case and its lifecycle state."""

    id: UUID
    candidate_id: UUID
    position_id: UUID
    start_date: date
    status: OnboardingCaseStatus


@dataclass(frozen=True)
class OnboardingState:
    """The disposable business state for one onboarding scenario."""

    candidates: tuple[Candidate, ...] = ()
    positions: tuple[Position, ...] = ()
    worker_records: tuple[WorkerRecord, ...] = ()
    checklist_templates: tuple[ChecklistTemplate, ...] = ()
    tasks: tuple[OnboardingTask, ...] = ()
    cases: tuple[OnboardingCase, ...] = ()
    policies: tuple[OnboardingPolicyDocument, ...] = ()


@dataclass(frozen=True)
class DependencyCoverage:
    """One dependency a scenario needs to run safely in the lab."""

    dependency: str
    kind: str  # "recorded" or "stateful"
    tools: tuple[str, ...]


@dataclass(frozen=True)
class ComparisonVariable:
    """The single baseline/candidate change the lab should compare."""

    name: str
    baseline: str
    candidate: str


@dataclass(frozen=True)
class WorkflowScenario:
    """One offline scenario sketch that maps to the lab's SimulationScenario."""

    scenario_id: str
    title: str
    category: ScenarioCategory
    actor_id: UUID
    request_message: str
    workflow_version: str
    eligible_actions: tuple[str, ...]
    initial_state: OnboardingState
    expected_outcome: ScenarioOutcome
    expected_reason_codes: tuple[ReasonCode, ...]
    permitted_state_transitions: tuple[str, ...]
    dependency_coverage: tuple[DependencyCoverage, ...]
    performance_budget_ms: int | None = None
    content_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        """Store the stable content hash of this scenario."""
        payload = {key: value for key, value in asdict(self).items() if key != "content_hash"}
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        object.__setattr__(self, "content_hash", sha256(canonical.encode()).hexdigest())


CURRENT_CHECKLIST_POLICY = """# Onboarding Compliance Checklist Policy

Policy version: 2026-08-01

Every new hire must complete identity verification (Form I-9), a background
check, payroll enrollment, and IT access provisioning before the first pay
cycle. Locations with E-Verify requirements add an E-Verify case in addition
to the Form I-9. Worker records must stay in draft until an HR manager
confirms the position, compensation tier, and start date. Onboarding is
complete only when every required task is completed.
"""

PREVIOUS_CHECKLIST_POLICY = """# Onboarding Compliance Checklist Policy

Policy version: 2026-02-01

Every new hire must complete a background check and payroll enrollment before
the first pay cycle. A single standard checklist applies to all locations.
Worker records are created directly as active records at intake.
"""

CURRENT_POLICY = OnboardingPolicyDocument(
    id=seed_id("policy:onboarding-checklist:2026-08-01"),
    slug="onboarding-checklist",
    version=ChecklistPolicyVersion.CURRENT,
    title="Onboarding Compliance Checklist Policy",
    content=CURRENT_CHECKLIST_POLICY,
    content_hash=content_hash(CURRENT_CHECKLIST_POLICY),
)

PREVIOUS_POLICY = OnboardingPolicyDocument(
    id=seed_id("policy:onboarding-checklist:2026-02-01"),
    slug="onboarding-checklist",
    version=ChecklistPolicyVersion.PREVIOUS,
    title="Onboarding Compliance Checklist Policy",
    content=PREVIOUS_CHECKLIST_POLICY,
    content_hash=content_hash(PREVIOUS_CHECKLIST_POLICY),
)

JORDAN = Candidate(
    id=seed_id("candidate:jordan-lee"),
    name="Jordan Lee",
    email="jordan.lee@example.test",
    work_authorization_verified=True,
)

PRIYA = Candidate(
    id=seed_id("candidate:priya-nair"),
    name="Priya Nair",
    email="priya.nair@example.test",
    work_authorization_verified=False,
)

POSITION_BE_ENG = Position(
    id=seed_id("position:backend-engineer-berlin"),
    title="Backend Engineer",
    department="Engineering",
    location="Berlin",
    compensation_tier="T4",
)

POSITION_DESIGNER_AUSTIN = Position(
    id=seed_id("position:product-designer-austin"),
    title="Product Designer",
    department="Design",
    location="Austin",
    compensation_tier="T3",
)

GENERIC_TEMPLATE = ChecklistTemplate(
    id=seed_id("template:generic-2026"),
    slug="generic",
    version="2026-08-01",
    title="Generic Onboarding Checklist",
    tasks=(
        "identity_verification_i9",
        "background_check",
        "payroll_enrollment",
        "it_access_provisioning",
    ),
    content_hash=content_hash("generic:" + CURRENT_CHECKLIST_POLICY),
)

LOCATION_TEMPLATE = ChecklistTemplate(
    id=seed_id("template:location-berlin-2026"),
    slug="location-berlin",
    version="2026-08-01",
    title="Berlin Onboarding Checklist",
    tasks=(
        "identity_verification_i9",
        "background_check",
        "payroll_enrollment",
        "it_access_provisioning",
        "everify_case",
    ),
    content_hash=content_hash("location-berlin:" + CURRENT_CHECKLIST_POLICY),
)

CASE_JORDAN = OnboardingCase(
    id=seed_id("case:jordan-lee"),
    candidate_id=JORDAN.id,
    position_id=POSITION_BE_ENG.id,
    start_date=date(2026, 8, 17),
    status=OnboardingCaseStatus.INTAKE,
)

CASE_PRIYA = OnboardingCase(
    id=seed_id("case:priya-nair"),
    candidate_id=PRIYA.id,
    position_id=POSITION_DESIGNER_AUSTIN.id,
    start_date=date(2026, 8, 24),
    status=OnboardingCaseStatus.DRAFTING,
)

SAFE_TOOLS = (
    "get_candidate",
    "get_position",
    "get_worker_record",
    "get_checklist_template",
    "get_onboarding_policy",
    "get_case_status",
)

SENSITIVE_TOOLS = (
    "draft_worker_record",
    "activate_worker_record",
    "assign_position",
    "select_checklist",
    "complete_task",
    "request_everify_case",
    "escalate_to_hr",
)

STATE_TRANSITIONS = (
    "onboarding_case:intake->drafting",
    "onboarding_case:drafting->awaiting_review",
    "onboarding_case:awaiting_review->active",
    "onboarding_case:awaiting_review->blocked",
    "worker_record:draft->pending_review",
    "worker_record:pending_review->active",
    "onboarding_task:pending->completed",
)

CHECKLIST_SELECTION = ComparisonVariable(
    name="checklist_selection_source",
    baseline=(
        "The agent applies the single generic checklist template to every new "
        "hire, regardless of role or location."
    ),
    candidate=(
        "The agent selects the role- and location-specific checklist template, "
        "which adds the E-Verify case and other location compliance tasks."
    ),
)


def _state_jordan() -> OnboardingState:
    return OnboardingState(
        candidates=(JORDAN,),
        positions=(POSITION_BE_ENG,),
        cases=(CASE_JORDAN,),
        checklist_templates=(GENERIC_TEMPLATE, LOCATION_TEMPLATE),
        policies=(CURRENT_POLICY,),
    )


def _state_priya() -> OnboardingState:
    return OnboardingState(
        candidates=(PRIYA,),
        positions=(POSITION_DESIGNER_AUSTIN,),
        cases=(CASE_PRIYA,),
        checklist_templates=(GENERIC_TEMPLATE, LOCATION_TEMPLATE),
        policies=(CURRENT_POLICY,),
    )


SCENARIOS: tuple[WorkflowScenario, ...] = (
    WorkflowScenario(
        scenario_id="onboarding-01-missed-location-compliance",
        title="Generic checklist misses the E-Verify compliance task",
        category=ScenarioCategory.RETRIEVAL_FAILURE,
        actor_id=JORDAN.id,
        request_message=(
            "Jordan Lee starts as Backend Engineer in Berlin on August 17. "
            "Set up the onboarding checklist and mark identity verification "
            "complete once the Form I-9 is done."
        ),
        workflow_version=WORKFLOW_VERSION,
        eligible_actions=SAFE_TOOLS + SENSITIVE_TOOLS,
        initial_state=_state_jordan(),
        expected_outcome=ScenarioOutcome.BLOCKED,
        expected_reason_codes=(
            ReasonCode.COMPLIANCE_TASK_MISSED,
            ReasonCode.ESCALATED,
        ),
        permitted_state_transitions=(
            "onboarding_case:intake->drafting",
            "onboarding_case:drafting->awaiting_review",
            "onboarding_case:awaiting_review->blocked",
        ),
        dependency_coverage=(
            DependencyCoverage(
                "onboarding.database", "stateful", ("get_candidate", "select_checklist")
            ),
            DependencyCoverage("compliance.everify", "recorded", ("request_everify_case",)),
        ),
        performance_budget_ms=4000,
    ),
    WorkflowScenario(
        scenario_id="onboarding-02-record-auto-activation",
        title="Worker record activated before HR confirms compensation",
        category=ScenarioCategory.POLICY_FAILURE,
        actor_id=PRIYA.id,
        request_message=(
            "Priya Nair starts as Product Designer in Austin on August 24. "
            "Create her worker record at tier T4 and activate it."
        ),
        workflow_version=WORKFLOW_VERSION,
        eligible_actions=SAFE_TOOLS + SENSITIVE_TOOLS,
        initial_state=_state_priya(),
        expected_outcome=ScenarioOutcome.BLOCKED,
        expected_reason_codes=(
            ReasonCode.RECORD_ACTIVATION_BLOCKED_UNCONFIRMED,
            ReasonCode.COMPENSATION_MISMATCH,
        ),
        permitted_state_transitions=(
            "onboarding_case:intake->drafting",
            "onboarding_case:drafting->awaiting_review",
            "worker_record:draft->pending_review",
        ),
        dependency_coverage=(
            DependencyCoverage(
                "onboarding.database", "stateful", ("get_candidate", "draft_worker_record")
            ),
        ),
        performance_budget_ms=4000,
    ),
    WorkflowScenario(
        scenario_id="onboarding-03-payroll-not-ready",
        title="Onboarding closed before IT provisioning and payroll enrollment",
        category=ScenarioCategory.TOOL_FAILURE,
        actor_id=JORDAN.id,
        request_message=(
            "All of Jordan's onboarding steps are done. Close the case so he "
            "is ready for the first pay cycle."
        ),
        workflow_version=WORKFLOW_VERSION,
        eligible_actions=SAFE_TOOLS + SENSITIVE_TOOLS,
        initial_state=OnboardingState(
            candidates=(JORDAN,),
            positions=(POSITION_BE_ENG,),
            cases=(
                OnboardingCase(
                    id=CASE_JORDAN.id,
                    candidate_id=JORDAN.id,
                    position_id=POSITION_BE_ENG.id,
                    start_date=CASE_JORDAN.start_date,
                    status=OnboardingCaseStatus.DRAFTING,
                ),
            ),
            checklist_templates=(GENERIC_TEMPLATE, LOCATION_TEMPLATE),
            policies=(CURRENT_POLICY,),
        ),
        expected_outcome=ScenarioOutcome.BLOCKED,
        expected_reason_codes=(
            ReasonCode.PAYROLL_NOT_READY,
            ReasonCode.ESCALATED,
        ),
        permitted_state_transitions=(
            "onboarding_case:awaiting_review->blocked",
            "onboarding_task:pending->completed",
        ),
        dependency_coverage=(
            DependencyCoverage(
                "onboarding.database", "stateful", ("get_case_status", "complete_task")
            ),
            DependencyCoverage("hr.payroll", "recorded", ("complete_task",)),
            DependencyCoverage("it.provisioning", "recorded", ("complete_task",)),
        ),
        performance_budget_ms=4000,
    ),
)

ALL_POLICIES: tuple[OnboardingPolicyDocument, ...] = (CURRENT_POLICY, PREVIOUS_POLICY)
ALL_CANDIDATES: tuple[Candidate, ...] = (JORDAN, PRIYA)
ALL_POSITIONS: tuple[Position, ...] = (POSITION_BE_ENG, POSITION_DESIGNER_AUSTIN)
ALL_TEMPLATES: tuple[ChecklistTemplate, ...] = (GENERIC_TEMPLATE, LOCATION_TEMPLATE)

COMPARISON_VARIABLE = CHECKLIST_SELECTION
ALL_DOCUMENTS = ALL_POLICIES
