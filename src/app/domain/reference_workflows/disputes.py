"""Deterministic offline fixture data for the banking dispute resolution agent.

This module is a self-contained reference fixture for the agent-observability
lab. It mirrors the shape of the customer-support seed data but stays fully
offline: no database, no network, no imports from ``app``. Every identifier is
a stable UUID derived from a fixed namespace, the regulation document carries a
sha256 content hash, and every scenario carries a stable content hash computed
from its canonical JSON. The lab can use this data to construct
``SimulationScenario`` and ``SimulationBundle`` records after the domain
mapping described in ``docs/reference_workflows/dispute-resolution-agent.md``.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid5

SEED_NAMESPACE = UUID("73c2b530-4d6e-5f80-ab1c-3e4f5a6b7c8d")

SCENARIO_ID_PREFIX = "disputes"
WORKFLOW_SLUG = "dispute_resolution_agent"
WORKFLOW_VERSION = "1.0.0"


def seed_id(name: str) -> UUID:
    """Return the stable UUID for one named fixture record."""
    return uuid5(SEED_NAMESPACE, name)


def content_hash(text: str) -> str:
    """Return the sha256 hex digest of one regulation document body."""
    return sha256(text.encode()).hexdigest()


class RegulationVersion(StrEnum):
    CURRENT = "2026-06-01"
    PREVIOUS = "2026-01-01"


class DisputeCategory(StrEnum):
    UNAUTHORIZED = "unauthorized"
    MERCHANT_ERROR = "merchant_error"
    PROCESSING_FAILURE = "processing_failure"
    FRIENDLY_FRAUD = "friendly_fraud"


class DisputeStatus(StrEnum):
    INTAKE = "intake"
    EVIDENCE_GATHERING = "evidence_gathering"
    DECISION_PENDING = "decision_pending"
    PROVISIONAL_CREDIT_ISSUED = "provisional_credit_issued"
    RESOLVED = "resolved"
    DENIED = "denied"
    ESCALATED = "escalated"


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
    DISPUTE_ACKNOWLEDGED = "dispute_acknowledged"
    ACK_TIMEOUT = "ack_timeout"
    EVIDENCE_COMPLETE = "evidence_complete"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    CREDIT_ISSUED = "credit_issued"
    CREDIT_BLOCKED_INSUFFICIENT_EVIDENCE = "credit_blocked_insufficient_evidence"
    DISPUTE_DENIED_FRIENDLY_FRAUD = "dispute_denied_friendly_fraud"
    DISPUTE_ESCALATED = "dispute_escalated"
    REGULATION_VERSION_STALE = "regulation_version_stale"
    MODEL_ERROR = "model_error"
    TOOL_ERROR = "tool_error"


@dataclass(frozen=True)
class RegulationDocument:
    """One versioned regulation (Regulation E / PSD2 style) timeline."""

    id: UUID
    slug: str
    version: str
    title: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class Customer:
    """One bank customer who may open a dispute."""

    id: UUID
    name: str
    email: str


@dataclass(frozen=True)
class Account:
    """One customer account that transactions post to."""

    id: UUID
    customer_id: UUID
    status: str


@dataclass(frozen=True)
class Transaction:
    """One posted transaction that may be disputed."""

    id: UUID
    account_id: UUID
    merchant: str
    amount: Decimal
    posted_at: date
    auth_method: str


@dataclass(frozen=True)
class FraudSignal:
    """One fraud-model output for a transaction."""

    id: UUID
    transaction_id: UUID
    signal_name: str
    score: float
    source: str


@dataclass(frozen=True)
class DisputeCase:
    """One dispute case and its lifecycle state."""

    id: UUID
    account_id: UUID
    transaction_id: UUID
    category: DisputeCategory
    status: DisputeStatus
    evidence_sources: tuple[str, ...]
    reg_e_ack_deadline: date
    ack_sent_at: date | None = None


@dataclass(frozen=True)
class DisputeState:
    """The disposable business state for one dispute scenario."""

    customers: tuple[Customer, ...] = ()
    accounts: tuple[Account, ...] = ()
    transactions: tuple[Transaction, ...] = ()
    fraud_signals: tuple[FraudSignal, ...] = ()
    cases: tuple[DisputeCase, ...] = ()
    regulations: tuple[RegulationDocument, ...] = ()


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
    initial_state: DisputeState
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


CURRENT_REGULATION_CONTENT = """# Consumer Dispute Timeline Regulation

Regulation version: 2026-06-01

A bank must acknowledge every dispute within 5 business days of intake and
resolve unauthorized-transaction claims within 45 days. For an unauthorized
claim, the bank must issue provisional credit within 1 business day after the
dispute is acknowledged unless the fraud signals indicate the cardholder was
involved. The agent must gather at least three evidence sources (transaction
record, fraud signals, and authentication events) before it recommends a
final decision. Any case that cannot meet these timelines must escalate.
"""

PREVIOUS_REGULATION_CONTENT = """# Consumer Dispute Timeline Regulation

Regulation version: 2026-01-01

A bank must acknowledge a dispute within 10 business days. Provisional credit
may be issued after a single evidence source is reviewed. Final resolution
must occur within 60 days.
"""

CURRENT_REGULATION = RegulationDocument(
    id=seed_id("regulation:dispute-timeline:2026-06-01"),
    slug="dispute-timeline",
    version=RegulationVersion.CURRENT,
    title="Consumer Dispute Timeline Regulation",
    content=CURRENT_REGULATION_CONTENT,
    content_hash=content_hash(CURRENT_REGULATION_CONTENT),
)

PREVIOUS_REGULATION = RegulationDocument(
    id=seed_id("regulation:dispute-timeline:2026-01-01"),
    slug="dispute-timeline",
    version=RegulationVersion.PREVIOUS,
    title="Consumer Dispute Timeline Regulation",
    content=PREVIOUS_REGULATION_CONTENT,
    content_hash=content_hash(PREVIOUS_REGULATION_CONTENT),
)

MARTA = Customer(
    id=seed_id("customer:marta-kovacs"),
    name="Marta Kovacs",
    email="marta.kovacs@example.test",
)

ACCOUNT_MARTA = Account(
    id=seed_id("account:marta-kovacs"),
    customer_id=MARTA.id,
    status="active",
)

TX_UNAUTHORIZED = Transaction(
    id=seed_id("transaction:tx-unauthorized"),
    account_id=ACCOUNT_MARTA.id,
    merchant="WispyPay Digital",
    amount=Decimal("320.00"),
    posted_at=date(2026, 7, 28),
    auth_method="card_not_present",
)

TX_FRIENDLY_FRAUD = Transaction(
    id=seed_id("transaction:tx-friendly-fraud"),
    account_id=ACCOUNT_MARTA.id,
    merchant="Corner Bistro",
    amount=Decimal("86.40"),
    posted_at=date(2026, 7, 25),
    auth_method="chip_pin",
)

SIGNAL_FRIENDLY = FraudSignal(
    id=seed_id("signal:tx-friendly-fraud-velocity"),
    transaction_id=TX_FRIENDLY_FRAUD.id,
    signal_name="cardholder_location_match",
    score=0.91,
    source="fraud.model.v3",
)

SIGNAL_UNAUTHORIZED = FraudSignal(
    id=seed_id("signal:tx-unauthorized-velocity"),
    transaction_id=TX_UNAUTHORIZED.id,
    signal_name="new_device_velocity",
    score=0.72,
    source="fraud.model.v3",
)

CASE_UNAUTHORIZED = DisputeCase(
    id=seed_id("case:tx-unauthorized"),
    account_id=ACCOUNT_MARTA.id,
    transaction_id=TX_UNAUTHORIZED.id,
    category=DisputeCategory.UNAUTHORIZED,
    status=DisputeStatus.INTAKE,
    evidence_sources=("ledger",),
    reg_e_ack_deadline=date(2026, 8, 6),
)

CASE_FRIENDLY_FRAUD = DisputeCase(
    id=seed_id("case:tx-friendly-fraud"),
    account_id=ACCOUNT_MARTA.id,
    transaction_id=TX_FRIENDLY_FRAUD.id,
    category=DisputeCategory.UNAUTHORIZED,
    status=DisputeStatus.EVIDENCE_GATHERING,
    evidence_sources=("ledger",),
    reg_e_ack_deadline=date(2026, 8, 4),
)

SAFE_TOOLS = (
    "get_account",
    "get_transaction",
    "get_fraud_signals",
    "get_auth_events",
    "get_dispute_timeline_regulation",
    "get_case_status",
)

SENSITIVE_TOOLS = (
    "acknowledge_dispute",
    "open_dispute_case",
    "issue_provisional_credit",
    "deny_dispute",
    "file_regulatory_notice",
    "escalate_to_reviewer",
)

STATE_TRANSITIONS = (
    "dispute_case:intake->evidence_gathering",
    "dispute_case:evidence_gathering->decision_pending",
    "dispute_case:decision_pending->provisional_credit_issued",
    "dispute_case:decision_pending->resolved",
    "dispute_case:decision_pending->denied",
    "dispute_case:evidence_gathering->escalated",
)

EVIDENCE_COMPLETENESS = ComparisonVariable(
    name="evidence_source_minimum",
    baseline=(
        "The agent recommends a decision after one evidence source (the ledger transaction record)."
    ),
    candidate=(
        "The agent gathers at least three evidence sources (transaction "
        "record, fraud signals, authentication events) before recommending "
        "a decision."
    ),
)


def _state_unauthorized() -> DisputeState:
    return DisputeState(
        customers=(MARTA,),
        accounts=(ACCOUNT_MARTA,),
        transactions=(TX_UNAUTHORIZED,),
        fraud_signals=(SIGNAL_UNAUTHORIZED,),
        cases=(CASE_UNAUTHORIZED,),
        regulations=(CURRENT_REGULATION,),
    )


def _state_friendly_fraud() -> DisputeState:
    return DisputeState(
        customers=(MARTA,),
        accounts=(ACCOUNT_MARTA,),
        transactions=(TX_FRIENDLY_FRAUD,),
        fraud_signals=(SIGNAL_FRIENDLY,),
        cases=(CASE_FRIENDLY_FRAUD,),
        regulations=(CURRENT_REGULATION,),
    )


SCENARIOS: tuple[WorkflowScenario, ...] = (
    WorkflowScenario(
        scenario_id="disputes-01-credit-on-single-source",
        title="Provisional credit issued on one evidence source",
        category=ScenarioCategory.RETRIEVAL_FAILURE,
        actor_id=MARTA.id,
        request_message=(
            "I did not make the 320.00 charge from WispyPay Digital on "
            "July 28. Please dispute it and give me my money back."
        ),
        workflow_version=WORKFLOW_VERSION,
        eligible_actions=SAFE_TOOLS + SENSITIVE_TOOLS,
        initial_state=_state_unauthorized(),
        expected_outcome=ScenarioOutcome.BLOCKED,
        expected_reason_codes=(
            ReasonCode.EVIDENCE_INCOMPLETE,
            ReasonCode.CREDIT_BLOCKED_INSUFFICIENT_EVIDENCE,
        ),
        permitted_state_transitions=(
            "dispute_case:intake->evidence_gathering",
            "dispute_case:evidence_gathering->decision_pending",
        ),
        dependency_coverage=(
            DependencyCoverage(
                "banking.database", "stateful", ("get_transaction", "open_dispute_case")
            ),
            DependencyCoverage("fraud.signals", "recorded", ("get_fraud_signals",)),
            DependencyCoverage("auth.events", "recorded", ("get_auth_events",)),
        ),
        performance_budget_ms=5000,
    ),
    WorkflowScenario(
        scenario_id="disputes-02-reg-e-ack-timeout",
        title="Regulation E acknowledgment misses the five-day deadline",
        category=ScenarioCategory.LATENCY_FAILURE,
        actor_id=MARTA.id,
        request_message=(
            "Why has nobody confirmed my dispute from July 28? I filed it five business days ago."
        ),
        workflow_version=WORKFLOW_VERSION,
        eligible_actions=SAFE_TOOLS + SENSITIVE_TOOLS,
        initial_state=_state_unauthorized(),
        expected_outcome=ScenarioOutcome.ESCALATED,
        expected_reason_codes=(
            ReasonCode.ACK_TIMEOUT,
            ReasonCode.DISPUTE_ESCALATED,
        ),
        permitted_state_transitions=(
            "dispute_case:intake->evidence_gathering",
            "dispute_case:evidence_gathering->escalated",
        ),
        dependency_coverage=(
            DependencyCoverage(
                "banking.database", "stateful", ("get_case_status", "acknowledge_dispute")
            ),
            DependencyCoverage("clock", "recorded", ("acknowledge_dispute",)),
        ),
        performance_budget_ms=5000,
    ),
    WorkflowScenario(
        scenario_id="disputes-03-friendly-fraud-credited",
        title="Cardholder-present transaction misclassified as unauthorized",
        category=ScenarioCategory.ANSWER_FAILURE,
        actor_id=MARTA.id,
        request_message=("I want to dispute the 86.40 charge at Corner Bistro. It was not mine."),
        workflow_version=WORKFLOW_VERSION,
        eligible_actions=SAFE_TOOLS + SENSITIVE_TOOLS,
        initial_state=_state_friendly_fraud(),
        expected_outcome=ScenarioOutcome.BLOCKED,
        expected_reason_codes=(
            ReasonCode.DISPUTE_DENIED_FRIENDLY_FRAUD,
            ReasonCode.CREDIT_BLOCKED_INSUFFICIENT_EVIDENCE,
        ),
        permitted_state_transitions=(
            "dispute_case:evidence_gathering->decision_pending",
            "dispute_case:decision_pending->denied",
        ),
        dependency_coverage=(
            DependencyCoverage("banking.database", "stateful", ("get_transaction", "deny_dispute")),
            DependencyCoverage("fraud.signals", "recorded", ("get_fraud_signals",)),
            DependencyCoverage("auth.events", "recorded", ("get_auth_events",)),
        ),
        performance_budget_ms=5000,
    ),
)

ALL_REGULATIONS: tuple[RegulationDocument, ...] = (CURRENT_REGULATION, PREVIOUS_REGULATION)
ALL_CUSTOMERS: tuple[Customer, ...] = (MARTA,)
ALL_ACCOUNTS: tuple[Account, ...] = (ACCOUNT_MARTA,)
ALL_TRANSACTIONS: tuple[Transaction, ...] = (TX_UNAUTHORIZED, TX_FRIENDLY_FRAUD)
ALL_FRAUD_SIGNALS: tuple[FraudSignal, ...] = (SIGNAL_UNAUTHORIZED, SIGNAL_FRIENDLY)
ALL_CASES: tuple[DisputeCase, ...] = (CASE_UNAUTHORIZED, CASE_FRIENDLY_FRAUD)

COMPARISON_VARIABLE = EVIDENCE_COMPLETENESS
ALL_DOCUMENTS = ALL_REGULATIONS
