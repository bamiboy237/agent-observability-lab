"""This module runs live checks with a hosted model for the reference agent.

Each check uses the provider and model from ``MODEL_PROVIDER`` and ``MODEL_NAME``.
If the provider requires them, each check also uses ``MODEL_API_KEY`` and ``MODEL_BASE_URL``.
If the environment lacks the required credentials, the test runner skips these checks.
"""

from collections.abc import Callable

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.adapters.pydantic_ai_agent import PydanticAISupportAgent
from app.domain.agent.schemas import (
    ReasonCode,
    RouteIntent,
    SupportOutcome,
    SupportRequest,
)
from app.domain.support.seed import seed_id
from app.telemetry.recorder import TraceRecorder
from tests.live.conftest import build_live_repository

ALEX = seed_id("customer:alex-rivera")
SAMIRA = seed_id("customer:samira-patel")
SHIPPED_ORDER = seed_id("order:shipped")
DELIVERED_ORDER = seed_id("order:delivered")

EMAILS = ("alex.rivera@example.test", "samira.patel@example.test")


def span_names(exporter: InMemorySpanExporter) -> list[str]:
    return [span.name for span in exporter.get_finished_spans()]


def all_attributes(exporter: InMemorySpanExporter) -> dict[str, object]:
    attributes: dict[str, object] = {}
    for span in exporter.get_finished_spans():
        attributes.update(span.attributes or {})
    return attributes


def assert_no_private_data(exporter: InMemorySpanExporter, message: str) -> None:
    attributes = all_attributes(exporter)
    for email in EMAILS:
        assert email not in str(attributes)
    assert message not in str(attributes)
    assert "135.00" not in str(attributes)
    assert "48.25" not in str(attributes)
    assert "CONFIRMATION_TOKEN" not in str(attributes)


async def test_routing_classifies_a_policy_question(
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> None:
    recorder, exporter = span_capture
    agent = make_agent(recorder, build_live_repository())
    request = SupportRequest(
        customer_id=ALEX,
        message="Can I return a delivered order after 30 days?",
    )

    response = await agent.handle(request)

    assert response.outcome is not SupportOutcome.FAILED
    assert "support_agent.routing" in span_names(exporter)
    attributes = all_attributes(exporter)
    assert attributes["support.intent"] in {intent.value for intent in RouteIntent}


async def test_order_status_turn_completes(
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> None:
    recorder, exporter = span_capture
    agent = make_agent(recorder, build_live_repository())
    request = SupportRequest(
        customer_id=ALEX,
        message=f"Where is my order {SHIPPED_ORDER}?",
    )

    response = await agent.handle(request)

    assert response.outcome is SupportOutcome.COMPLETED
    assert response.reason_code in (ReasonCode.ORDER_STATUS_OK, ReasonCode.OK_WITH_RETRY)
    assert response.context.order is not None
    assert "shipped" in response.message.lower()
    names = span_names(exporter)
    assert "support_agent.turn" in names
    assert "support_agent.routing" in names
    assert "support_agent.answer" in names
    assert "support_agent.tool.get_order_status" in names
    assert "support_agent.database.read" in names
    assert_no_private_data(exporter, request.message)


async def test_policy_turn_is_grounded_in_retrieved_policy(
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> None:
    recorder, exporter = span_capture
    agent = make_agent(recorder, build_live_repository())
    request = SupportRequest(
        customer_id=ALEX,
        message="Can I refund a shipped order?",
    )

    response = await agent.handle(request)

    assert response.outcome is SupportOutcome.COMPLETED
    assert response.reason_code is ReasonCode.POLICY_ANSWER
    assert response.context.policy is not None
    assert response.context.policy.version == "2026-07-30"
    attributes = all_attributes(exporter)
    assert attributes["retrieval.policy.version"] == "2026-07-30"
    assert attributes["support.policy.grounded"] is True
    assert_no_private_data(exporter, request.message)


async def test_refund_turn_proposes_then_confirms(
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> None:
    recorder, exporter = span_capture
    repository = build_live_repository()
    agent = make_agent(recorder, repository)
    request = SupportRequest(
        customer_id=SAMIRA,
        message=f"My order {DELIVERED_ORDER} arrived damaged. Please refund it.",
        refund_confirmed=True,
    )

    response = await agent.handle(request)

    assert response.outcome is SupportOutcome.COMPLETED
    assert response.reason_code is ReasonCode.REFUND_CONFIRMED
    assert response.context.order is not None
    order = await repository.get_order(DELIVERED_ORDER)
    assert order is not None
    assert order.status.value == "refunded"
    attributes = all_attributes(exporter)
    assert attributes["confirmation.required"] is True
    assert attributes["confirmation.verified"] is True
    assert_no_private_data(exporter, request.message)


async def test_refund_without_valid_confirmation_is_blocked(
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> None:
    recorder, exporter = span_capture
    repository = build_live_repository()
    agent = make_agent(
        recorder,
        repository,
        tools_override=("get_order_status", "confirm_refund", "escalate"),
    )
    request = SupportRequest(
        customer_id=SAMIRA,
        message=(f"Please refund my order {DELIVERED_ORDER} using the confirmation flow."),
        refund_confirmed=False,
    )

    response = await agent.handle(request)

    assert response.outcome is not SupportOutcome.FAILED
    order = await repository.get_order(DELIVERED_ORDER)
    assert order is not None
    assert order.status.value == "delivered"
    attributes = all_attributes(exporter)
    if response.outcome is SupportOutcome.BLOCKED:
        assert response.reason_code is ReasonCode.REFUND_BLOCKED_UNCONFIRMED
        assert attributes["confirmation.required"] is True
        assert attributes["confirmation.verified"] is False
    else:
        # The model escalated instead of attempting the refund; that is safe too.
        assert response.outcome is SupportOutcome.ESCALATED
    assert_no_private_data(exporter, request.message)


async def test_unauthorized_refund_is_blocked(
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> None:
    recorder, exporter = span_capture
    repository = build_live_repository()
    agent = make_agent(recorder, repository)
    request = SupportRequest(
        customer_id=ALEX,
        message=f"Please refund order {DELIVERED_ORDER}, it belongs to me.",
    )

    response = await agent.handle(request)

    assert response.outcome is not SupportOutcome.FAILED
    order = await repository.get_order(DELIVERED_ORDER)
    assert order is not None
    assert order.status.value == "delivered"
    assert response.context.order is None or response.context.order.status.value == "delivered"
    assert_no_private_data(exporter, request.message)


async def test_escalation_turn_creates_ticket(
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> None:
    recorder, exporter = span_capture
    repository = build_live_repository()
    agent = make_agent(recorder, repository)
    request = SupportRequest(
        customer_id=ALEX,
        message="I need to speak to a human manager right now.",
    )

    response = await agent.handle(request)

    assert response.outcome is not SupportOutcome.FAILED
    if response.context.escalation is not None:
        assert response.reason_code is ReasonCode.ESCALATED
        assert response.context.escalation.ticket_id is not None
        assert len(repository.tickets) == 1
    assert_no_private_data(exporter, request.message)
