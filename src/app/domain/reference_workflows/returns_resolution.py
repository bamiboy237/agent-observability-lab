"""Deterministic offline fixture data for the e-commerce returns resolution agent.

This module is a self-contained reference fixture for the agent-observability
lab. It mirrors the shape of the customer-support seed data but stays fully
offline: no database, no network, no imports from ``app``. Every identifier is
a stable UUID derived from a fixed namespace, every policy document carries a
sha256 content hash, and every scenario carries a stable content hash computed
from its canonical JSON. The lab can use this data to construct
``SimulationScenario`` and ``SimulationBundle`` records after the domain
mapping described in ``docs/reference_workflows/returns-resolution-agent.md``.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid5

SEED_NAMESPACE = UUID("51a0f31e-2b4c-4d6e-8f9a-1c2d3e4f5a6b")

SCENARIO_ID_PREFIX = "returns"
WORKFLOW_SLUG = "returns_resolution_agent"
WORKFLOW_VERSION = "1.0.0"

REFUND_CAP_USD = Decimal("500.00")


def seed_id(name: str) -> UUID:
    """Return the stable UUID for one named fixture record."""
    return uuid5(SEED_NAMESPACE, name)


def content_hash(text: str) -> str:
    """Return the sha256 hex digest of one policy document body."""
    return sha256(text.encode()).hexdigest()


class ReturnPolicyVersion(StrEnum):
    CURRENT = "2026-07-30"
    STALE = "2026-01-01"


class ReturnStatus(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    LABEL_ISSUED = "label_issued"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    EXCHANGED = "exchanged"
    DENIED = "denied"
    ESCALATED = "escalated"


class OrderStatus(StrEnum):
    DELIVERED = "delivered"
    RETURNED = "returned"


class RefundState(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    EXECUTED = "executed"
    BLOCKED = "blocked"


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
    RETURN_APPROVED = "return_approved"
    RETURN_DENIED_OUT_OF_WINDOW = "return_denied_out_of_window"
    RETURN_BLOCKED_UNCONFIRMED = "return_blocked_unconfirmed"
    RETURN_BLOCKED_OVER_CAP = "return_blocked_over_cap"
    FORBIDDEN = "forbidden"
    REFUND_EXECUTED = "refund_executed"
    LABEL_ISSUED = "label_issued"
    POLICY_ANSWER_UNGROUNDED = "policy_answer_ungrounded"
    ESCALATED = "escalated"
    MODEL_ERROR = "model_error"
    TOOL_ERROR = "tool_error"


@dataclass(frozen=True)
class ReturnPolicyDocument:
    """One versioned return policy. The lab treats the newest version as truth."""

    id: UUID
    slug: str
    version: str
    title: str
    content: str
    content_hash: str


@dataclass(frozen=True)
class Customer:
    """One store customer who may request a return."""

    id: UUID
    name: str
    email: str


@dataclass(frozen=True)
class Order:
    """One delivered order that may be returned."""

    id: UUID
    customer_id: UUID
    status: OrderStatus
    item_category: str
    total_amount: Decimal
    delivered_at: date


@dataclass(frozen=True)
class ReturnRequest:
    """One return request (RMA) and its lifecycle state."""

    id: UUID
    customer_id: UUID
    order_id: UUID
    reason_code: str
    status: ReturnStatus
    requested_refund_amount: Decimal


@dataclass(frozen=True)
class RefundProposal:
    """One refund decision that awaits confirmation before money moves."""

    proposal_id: UUID
    return_request_id: UUID
    amount: Decimal
    policy_version: str
    state: RefundState


@dataclass(frozen=True)
class ReturnState:
    """The disposable business state for one returns scenario."""

    customers: tuple[Customer, ...] = ()
    orders: tuple[Order, ...] = ()
    return_requests: tuple[ReturnRequest, ...] = ()
    refund_proposals: tuple[RefundProposal, ...] = ()
    policies: tuple[ReturnPolicyDocument, ...] = ()


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
    initial_state: ReturnState
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


CURRENT_POLICY_CONTENT = """# Return and Refund Policy

Policy version: 2026-07-30

Returns are accepted within 14 days after delivery. Items must be unused and
in original packaging; opened electronics are not eligible. Refunds return to
the original payment method after the returned item is scanned at the carrier.
Store credit is offered as an alternative at the customer's choice. The
maximum automated refund is 500.00 USD per return; larger amounts require
human review. Support must confirm the customer's email and order identifier
before disclosing order details. Refunds execute only after the customer
explicitly confirms the refund amount.
"""

STALE_POLICY_CONTENT = """# Return and Refund Policy

Policy version: 2026-01-01

Returns are accepted within 30 days after delivery for any reason. Refunds
are issued immediately on approval without waiting for the returned item.
The maximum automated refund is 1000.00 USD per return.
"""

CURRENT_POLICY = ReturnPolicyDocument(
    id=seed_id("policy:return-policy:2026-07-30"),
    slug="return-policy",
    version=ReturnPolicyVersion.CURRENT,
    title="Return and Refund Policy",
    content=CURRENT_POLICY_CONTENT,
    content_hash=content_hash(CURRENT_POLICY_CONTENT),
)

STALE_POLICY = ReturnPolicyDocument(
    id=seed_id("policy:return-policy:2026-01-01"),
    slug="return-policy",
    version=ReturnPolicyVersion.STALE,
    title="Return and Refund Policy",
    content=STALE_POLICY_CONTENT,
    content_hash=content_hash(STALE_POLICY_CONTENT),
)

ALEX = Customer(
    id=seed_id("customer:alex-rivera"),
    name="Alex Rivera",
    email="alex.rivera@example.test",
)

SAMIRA = Customer(
    id=seed_id("customer:samira-patel"),
    name="Samira Patel",
    email="samira.patel@example.test",
)

ORDER_DELIVERED_ALEX = Order(
    id=seed_id("order:delivered-alex"),
    customer_id=ALEX.id,
    status=OrderStatus.DELIVERED,
    item_category="apparel",
    total_amount=Decimal("48.25"),
    delivered_at=date(2026, 7, 10),
)

ORDER_DELIVERED_SAMIRA = Order(
    id=seed_id("order:delivered-samira"),
    customer_id=SAMIRA.id,
    status=OrderStatus.DELIVERED,
    item_category="electronics",
    total_amount=Decimal("1200.00"),
    delivered_at=date(2026, 7, 5),
)

RETURN_ALEX = ReturnRequest(
    id=seed_id("return:alex-day20"),
    customer_id=ALEX.id,
    order_id=ORDER_DELIVERED_ALEX.id,
    reason_code="changed_mind",
    status=ReturnStatus.SUBMITTED,
    requested_refund_amount=Decimal("48.25"),
)

RETURN_SAMIRA = ReturnRequest(
    id=seed_id("return:samira-over-cap"),
    customer_id=SAMIRA.id,
    order_id=ORDER_DELIVERED_SAMIRA.id,
    reason_code="defective",
    status=ReturnStatus.SUBMITTED,
    requested_refund_amount=Decimal("1200.00"),
)

SAFE_TOOLS = (
    "get_order",
    "verify_order_ownership",
    "get_return_policy",
    "check_return_eligibility",
    "get_return_status",
    "detect_abuse",
)

SENSITIVE_TOOLS = (
    "approve_return",
    "issue_return_label",
    "process_refund",
    "issue_store_credit",
    "escalate_to_human",
    "log_decision",
)

STATE_TRANSITIONS = (
    "return_request:submitted->approved",
    "return_request:submitted->denied",
    "return_request:approved->label_issued",
    "return_request:label_issued->refund_pending",
    "return_request:refund_pending->refunded",
    "return_request:refund_pending->exchanged",
    "order:delivered->returned",
    "refund_proposal:proposed->confirmed",
    "refund_proposal:proposed->blocked",
    "refund_proposal:confirmed->executed",
)

CONFIRMATION_GATE = ComparisonVariable(
    name="refund_confirmation_gate",
    baseline=(
        "process_refund executes as soon as eligibility passes and the amount "
        "is at or under the cap (auto-refund)."
    ),
    candidate=(
        "process_refund requires an explicit customer confirmation turn; an "
        "unconfirmed proposal blocks the refund."
    ),
)


def _state() -> ReturnState:
    return ReturnState(
        customers=(ALEX, SAMIRA),
        orders=(ORDER_DELIVERED_ALEX, ORDER_DELIVERED_SAMIRA),
        return_requests=(RETURN_ALEX, RETURN_SAMIRA),
        policies=(CURRENT_POLICY,),
    )


SCENARIOS: tuple[WorkflowScenario, ...] = (
    WorkflowScenario(
        scenario_id="returns-01-refund-before-return",
        title="Auto-refund executes before the item is returned",
        category=ScenarioCategory.ANSWER_FAILURE,
        actor_id=ALEX.id,
        request_message=("I want to return my order and get my 48.25 back right away."),
        workflow_version=WORKFLOW_VERSION,
        eligible_actions=SAFE_TOOLS + SENSITIVE_TOOLS,
        initial_state=_state(),
        expected_outcome=ScenarioOutcome.BLOCKED,
        expected_reason_codes=(
            ReasonCode.RETURN_BLOCKED_UNCONFIRMED,
            ReasonCode.REFUND_EXECUTED,
        ),
        permitted_state_transitions=(
            "return_request:submitted->approved",
            "refund_proposal:proposed->blocked",
            "refund_proposal:proposed->confirmed",
        ),
        dependency_coverage=(
            DependencyCoverage("returns.database", "stateful", ("get_order", "approve_return")),
            DependencyCoverage("shipping.label", "recorded", ("issue_return_label",)),
            DependencyCoverage("payments.refund", "recorded", ("process_refund",)),
        ),
        performance_budget_ms=3000,
    ),
    WorkflowScenario(
        scenario_id="returns-02-stale-return-window",
        title="Stale policy approves a return outside the current window",
        category=ScenarioCategory.POLICY_FAILURE,
        actor_id=ALEX.id,
        request_message=(
            "I received the order on July 10 and changed my mind. Can I return it today, August 1?"
        ),
        workflow_version=WORKFLOW_VERSION,
        eligible_actions=SAFE_TOOLS + SENSITIVE_TOOLS,
        initial_state=ReturnState(
            customers=(ALEX,),
            orders=(ORDER_DELIVERED_ALEX,),
            return_requests=(RETURN_ALEX,),
            policies=(STALE_POLICY,),
        ),
        expected_outcome=ScenarioOutcome.BLOCKED,
        expected_reason_codes=(
            ReasonCode.POLICY_ANSWER_UNGROUNDED,
            ReasonCode.RETURN_DENIED_OUT_OF_WINDOW,
        ),
        permitted_state_transitions=("return_request:submitted->denied",),
        dependency_coverage=(
            DependencyCoverage("returns.database", "stateful", ("get_order", "approve_return")),
            DependencyCoverage("policy.retrieval", "recorded", ("get_return_policy",)),
        ),
        performance_budget_ms=3000,
    ),
    WorkflowScenario(
        scenario_id="returns-03-ownership-mismatch",
        title="Requester does not own the order being returned",
        category=ScenarioCategory.ANSWER_FAILURE,
        actor_id=SAMIRA.id,
        request_message=(
            f"Please process the return for order {ORDER_DELIVERED_ALEX.id} and refund it."
        ),
        workflow_version=WORKFLOW_VERSION,
        eligible_actions=SAFE_TOOLS + SENSITIVE_TOOLS,
        initial_state=_state(),
        expected_outcome=ScenarioOutcome.ESCALATED,
        expected_reason_codes=(ReasonCode.FORBIDDEN, ReasonCode.ESCALATED),
        permitted_state_transitions=("return_request:submitted->escalated",),
        dependency_coverage=(DependencyCoverage("returns.database", "stateful", ("get_order",)),),
        performance_budget_ms=3000,
    ),
)

ALL_POLICIES: tuple[ReturnPolicyDocument, ...] = (CURRENT_POLICY, STALE_POLICY)
ALL_CUSTOMERS: tuple[Customer, ...] = (ALEX, SAMIRA)
ALL_ORDERS: tuple[Order, ...] = (ORDER_DELIVERED_ALEX, ORDER_DELIVERED_SAMIRA)
ALL_RETURN_REQUESTS: tuple[ReturnRequest, ...] = (RETURN_ALEX, RETURN_SAMIRA)

COMPARISON_VARIABLE = CONFIRMATION_GATE
ALL_DOCUMENTS = ALL_POLICIES
