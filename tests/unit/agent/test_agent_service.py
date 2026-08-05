"""This module checks deterministic rules for agent ownership, refunds, and confirmation.

These tests exercise the guard service between the model and the Phase 1 support service.
These tests never call a model.
These tests verify that the guard service blocks model output from bypassing
ownership checks, the refund policy, or confirmation rules.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.domain.agent.errors import RefundNotConfirmed
from app.domain.agent.instructions import ACCEPTED_POLICY_VERSION, POLICY_SLUG
from app.domain.agent.schemas import ReasonCode, RouteIntent, RoutingDecision, SupportOutcome
from app.domain.agent.service import SupportAgentService, escalate_turn
from app.domain.support.errors import Forbidden, InvalidTransition, OrderNotFound
from app.domain.support.schemas import OrderRead, OrderStatus, PolicyDocumentRead
from app.domain.support.service import SupportService
from app.telemetry.recorder import TraceRecorder
from tests.fakes.support_repository import InMemorySupportRepository

DISABLED_RECORDER = TraceRecorder(None)


def make_order(status: OrderStatus = OrderStatus.DELIVERED) -> OrderRead:
    return OrderRead(
        id=uuid4(),
        customer_id=uuid4(),
        status=status,
        total_amount=Decimal("48.25"),
    )


def make_policy(version: str = ACCEPTED_POLICY_VERSION) -> PolicyDocumentRead:
    return PolicyDocumentRead(
        id=uuid4(),
        slug=POLICY_SLUG,
        version=version,
        title="Refund and Delivery Policy",
        content="# Policy\nDelivered orders are refundable.",
        content_hash="hash",
    )


def make_service(
    orders: tuple[OrderRead, ...] = (),
    policies: tuple[PolicyDocumentRead, ...] = (),
    customer_id: UUID | None = None,
    refund_confirmed: bool = False,
) -> tuple[SupportAgentService, InMemorySupportRepository]:
    repository = InMemorySupportRepository(orders=orders, policies=policies)
    agent_service = SupportAgentService(
        SupportService(repository),
        customer_id=customer_id or (orders[0].customer_id if orders else uuid4()),
        recorder=DISABLED_RECORDER,
        refund_confirmed=refund_confirmed,
    )
    return agent_service, repository


async def test_owner_can_read_order_status() -> None:
    order = make_order()
    service, _ = make_service((order,), customer_id=order.customer_id)

    result = await service.get_order_status(order.id)

    assert result == order
    assert service.last_order == order


async def test_other_customer_cannot_read_order() -> None:
    order = make_order()
    service, _ = make_service((order,), customer_id=uuid4())

    with pytest.raises(Forbidden):
        await service.get_order_status(order.id)


async def test_missing_order_raises_order_not_found() -> None:
    service, _ = make_service(customer_id=uuid4())

    with pytest.raises(OrderNotFound):
        await service.get_order_status(uuid4())


async def test_delivered_order_proposal_records_policy_version() -> None:
    order = make_order(OrderStatus.DELIVERED)
    service, _ = make_service((order,), policies=(make_policy(),), customer_id=order.customer_id)

    proposal = await service.propose_refund(order.id, "arrived damaged")

    assert proposal.order_id == order.id
    assert proposal.customer_id == order.customer_id
    assert proposal.amount == order.total_amount
    assert proposal.policy_version == ACCEPTED_POLICY_VERSION
    assert service.pending_proposal(order.id) == proposal


async def test_non_delivered_order_cannot_be_proposed() -> None:
    for status in OrderStatus:
        if status is OrderStatus.DELIVERED:
            continue
        order = make_order(status)
        service, repository = make_service((order,), customer_id=order.customer_id)

        with pytest.raises(InvalidTransition):
            await service.propose_refund(order.id, "changed my mind")

        assert await repository.get_order(order.id) == order
        assert service.pending_proposal(order.id) is None


async def test_another_customer_cannot_propose_refund() -> None:
    order = make_order()
    service, _ = make_service((order,), customer_id=uuid4())

    with pytest.raises(Forbidden):
        await service.propose_refund(order.id, "not my order")


async def test_confirm_requires_trusted_request_confirmation() -> None:
    order = make_order()
    service, repository = make_service((order,), customer_id=order.customer_id)
    await service.propose_refund(order.id, "damaged")

    with pytest.raises(RefundNotConfirmed):
        await service.confirm_refund(order.id)

    assert await repository.get_order(order.id) == order

    confirmed_service, _ = make_service(
        (order,), customer_id=order.customer_id, refund_confirmed=True
    )
    await confirmed_service.propose_refund(order.id, "damaged")
    refunded = await confirmed_service.confirm_refund(order.id)

    assert refunded.status is OrderStatus.REFUNDED
    assert confirmed_service.confirmed_refund_for(order.id) == refunded


async def test_confirm_without_proposal_is_rejected() -> None:
    order = make_order()
    service, repository = make_service((order,), customer_id=order.customer_id)

    with pytest.raises(RefundNotConfirmed):
        await service.confirm_refund(order.id)

    order_after = await repository.get_order(order.id)
    assert order_after == order


async def test_confirmation_cannot_be_reused() -> None:
    order = make_order()
    service, repository = make_service(
        (order,), customer_id=order.customer_id, refund_confirmed=True
    )
    await service.propose_refund(order.id, "damaged")
    await service.confirm_refund(order.id)

    with pytest.raises(RefundNotConfirmed):
        await service.confirm_refund(order.id)

    order_after = await repository.get_order(order.id)
    assert order_after is not None
    assert order_after.status is OrderStatus.REFUNDED


async def test_policy_lookup_returns_latest_version() -> None:
    service, _ = make_service(
        policies=(make_policy("2025-01-01"), make_policy(ACCEPTED_POLICY_VERSION)),
        customer_id=uuid4(),
    )

    policy = await service.get_policy()

    assert policy.version == ACCEPTED_POLICY_VERSION
    assert service.retrieved_policy_version == ACCEPTED_POLICY_VERSION
    assert service.last_policy == policy


async def test_escalate_creates_ticket() -> None:
    customer_id = uuid4()
    service, repository = make_service(customer_id=customer_id)

    ticket = await service.escalate("Escalated support request (escalated)")

    assert ticket.customer_id == customer_id
    assert await repository.get_ticket(ticket.id) == ticket
    assert service.last_escalation is not None
    assert service.last_escalation.ticket_id == ticket.id


async def test_deterministic_escalated_turn_creates_ticket_without_model() -> None:
    customer_id = uuid4()
    service, repository = make_service(customer_id=customer_id)
    routing = RoutingDecision(intent=RouteIntent.ESCALATE, confidence=0.5)

    response = await escalate_turn(service, routing, ReasonCode.ESCALATED_MISSING_REFERENCE)

    assert response.outcome is SupportOutcome.ESCALATED
    assert response.intent is RouteIntent.ESCALATE
    assert response.reason_code is ReasonCode.ESCALATED_MISSING_REFERENCE
    assert response.context.escalation is not None
    assert len(response.message) > 0
    assert len(repository.tickets) == 1
