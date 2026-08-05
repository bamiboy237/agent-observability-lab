"""This module defines the typed contract for the reference agent and its instrumentation."""

from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.support.schemas import OrderRead, PolicyDocumentRead


class RouteIntent(StrEnum):
    """This enum defines the possible intents for a support turn."""

    REFUND = "refund"
    ORDER_STATUS = "order_status"
    POLICY = "policy"
    ESCALATE = "escalate"


class SupportOutcome(StrEnum):
    """This enum defines the stable outcome values for every response and trace."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    FAILED = "failed"


class ReasonCode(StrEnum):
    """This enum defines stable reason codes for responses and trace attributes."""

    ORDER_STATUS_OK = "order_status_ok"
    ORDER_NOT_FOUND = "order_not_found"
    FORBIDDEN = "forbidden"
    POLICY_ANSWER = "policy_answer"
    POLICY_ANSWER_UNGROUNDED = "policy_answer_ungrounded"
    REFUND_PROPOSED = "refund_proposed"
    REFUND_CONFIRMED = "refund_confirmed"
    REFUND_BLOCKED_UNCONFIRMED = "refund_blocked_unconfirmed"
    REFUND_BLOCKED_INELIGIBLE = "refund_blocked_ineligible"
    REFUND_BLOCKED_FORBIDDEN = "refund_blocked_forbidden"
    REFUND_BLOCKED_MISSING_REFERENCE = "refund_blocked_missing_reference"
    ESCALATED = "escalated"
    ESCALATED_MISSING_REFERENCE = "escalated_missing_reference"
    MODEL_ERROR = "model_error"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"
    OK_WITH_RETRY = "ok_with_retry"
    OK_SLOW = "ok_slow"


class SupportRequest(BaseModel):
    """This class stores one customer support turn.

    The ``message`` field contains unrestricted user text.
    The application must never record this field in traces.
    """

    customer_id: UUID
    message: str = Field(min_length=1, max_length=2000)
    refund_confirmed: bool = False


class RoutingDecision(BaseModel):
    """This class stores structured model output that routes a support request."""

    intent: RouteIntent
    confidence: float = Field(ge=0.0, le=1.0)
    order_id: UUID | None = None
    policy_slug: str | None = None


class RefundProposal(BaseModel):
    """This class stores a refund proposal that awaits explicit confirmation.

    Confirmation is a trusted request field. The model cannot set it.
    """

    proposal_id: UUID
    order_id: UUID
    customer_id: UUID
    amount: Decimal
    policy_version: str


class Escalation(BaseModel):
    """This class stores a human escalation as a support ticket."""

    ticket_id: UUID
    reason_code: ReasonCode


class AnswerContext(BaseModel):
    """This class stores all typed data that the agent gathers for one turn."""

    routing: RoutingDecision
    order: OrderRead | None = None
    policy: PolicyDocumentRead | None = None
    proposal: RefundProposal | None = None
    escalation: Escalation | None = None


class SupportResponse(BaseModel):
    """This class stores the result that the customer receives for one support turn."""

    intent: RouteIntent
    outcome: SupportOutcome
    reason_code: ReasonCode
    message: str = Field(min_length=1, max_length=4000)
    context: AnswerContext
    trace_id: str | None = None
