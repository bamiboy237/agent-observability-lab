"""Acceptance tests for the Phase 4 workflow service."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.support.schemas import OrderRead, OrderStatus, PolicyDocumentRead
from app.domain.workflow.errors import (
    InvalidWorkflowResume,
    WorkflowActorMismatch,
    WorkflowExpired,
)
from app.domain.workflow.models import WorkflowRequest
from app.domain.workflow.service import WorkflowService, default_dependencies
from app.telemetry.recorder import TraceRecorder
from tests.fakes.support_repository import InMemorySupportRepository


def make_service(order_status: OrderStatus = OrderStatus.DELIVERED) -> tuple[
    WorkflowService,
    InMemorySupportRepository,
    object,
]:
    actor_id = uuid4()
    order = OrderRead(
        id=uuid4(),
        customer_id=actor_id,
        status=order_status,
        total_amount=Decimal("48.25"),
    )
    policy = PolicyDocumentRead(
        id=uuid4(),
        slug="refund-and-delivery",
        version="2026-07-30",
        title="Refund policy",
        content="Refunds are available for delivered orders.",
        content_hash="a" * 64,
    )
    repository = InMemorySupportRepository((order,), (policy,))
    service = WorkflowService(
        default_dependencies(repository, TraceRecorder(None)),
    )
    return service, repository, (actor_id, order)


async def test_read_only_order_status_produces_transcript_without_mutation() -> None:
    service, repository, (actor_id, order) = make_service()

    result = await service.start(
        WorkflowRequest(
            actor_id=actor_id,
            request_id="status-1",
            message=f"Where is order {order.id}?",
        )
    )

    assert result.status == "completed"
    assert [item.node for item in result.state["transcript"]] == [
        "route",
        "retrieve_order",
        "respond",
    ]
    assert await repository.get_order(order.id) == order


async def test_policy_and_direct_escalation_paths_are_explicit() -> None:
    service, repository, (actor_id, _order) = make_service()

    policy = await service.start(
        WorkflowRequest(
            actor_id=actor_id,
            request_id="policy-1",
            message="What does the return policy say?",
        )
    )
    assert policy.status == "completed"
    assert [item.node for item in policy.state["transcript"]] == [
        "route",
        "retrieve_policy",
        "respond",
    ]

    escalation = await service.start(
        WorkflowRequest(
            actor_id=actor_id,
            request_id="escalate-1",
            message="I need help with an account problem.",
        )
    )
    assert escalation.status == "escalated"
    assert [item.node for item in escalation.state["transcript"]] == [
        "route",
        "escalate",
    ]
    assert len(repository.tickets) == 1


async def test_refund_interrupt_requires_matching_confirmation_and_executes_once() -> None:
    service, repository, (actor_id, order) = make_service()

    paused = await service.start(
        WorkflowRequest(
            actor_id=actor_id,
            request_id="refund-1",
            message=f"Please refund order {order.id}",
        )
    )
    assert paused.status == "awaiting_confirmation"
    assert paused.interrupted is True
    assert (await repository.get_order(order.id)).status is OrderStatus.DELIVERED

    completed = await service.confirm(paused.workflow_id, actor_id, "refund-1")
    assert completed.status == "completed"
    assert (await repository.get_order(order.id)).status is OrderStatus.REFUNDED

    with pytest.raises(InvalidWorkflowResume):
        await service.confirm(paused.workflow_id, actor_id, "refund-1")


async def test_rejection_wrong_actor_and_expired_resume_do_not_mutate() -> None:
    service, repository, (actor_id, order) = make_service()
    paused = await service.start(
        WorkflowRequest(
            actor_id=actor_id,
            request_id="refund-2",
            message=f"Please refund order {order.id}",
        )
    )

    with pytest.raises(WorkflowActorMismatch):
        await service.confirm(paused.workflow_id, uuid4(), "refund-2")
    assert (await repository.get_order(order.id)).status is OrderStatus.DELIVERED

    rejected = await service.reject(paused.workflow_id, actor_id, "refund-2")
    assert rejected.status == "rejected"
    assert (await repository.get_order(order.id)).status is OrderStatus.DELIVERED

    expired_service, expired_repo, (expired_actor, expired_order) = make_service()
    expired = await expired_service.start(
        WorkflowRequest(
            actor_id=expired_actor,
            request_id="refund-3",
            message=f"Please refund order {expired_order.id}",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    with pytest.raises(WorkflowExpired):
        await expired_service.confirm(expired.workflow_id, expired_actor, "refund-3")
    assert (await expired_repo.get_order(expired_order.id)).status is OrderStatus.DELIVERED


async def test_workflow_trace_has_interaction_graph_and_node_hierarchy() -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    _, repository, (actor_id, order) = make_service()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    service = WorkflowService(
        default_dependencies(repository, TraceRecorder(provider.get_tracer("workflow-test")))
    )

    await service.start(
        WorkflowRequest(
            actor_id=actor_id,
            request_id="trace-1",
            message=f"Where is order {order.id}?",
        )
    )
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert {
        "support.workflow.interaction",
        "support.workflow.graph",
        "support.workflow.node.route",
    } <= spans.keys()
    assert spans["support.workflow.graph"].parent.span_id == spans[
        "support.workflow.interaction"
    ].context.span_id
    assert spans["support.workflow.node.route"].parent.span_id == spans[
        "support.workflow.graph"
    ].context.span_id
