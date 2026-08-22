"""PostgreSQL checkpoint acceptance for the controlled workflow."""

from decimal import Decimal
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import ValidationError

from app.api.workflow_router import _psycopg_url
from app.config import Settings
from app.domain.support.schemas import OrderRead, OrderStatus, PolicyDocumentRead
from app.domain.workflow.models import WorkflowRequest
from app.domain.workflow.service import WorkflowService, default_dependencies
from app.telemetry.recorder import TraceRecorder
from tests.fakes.support_repository import InMemorySupportRepository


def _database_settings() -> Settings:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for database integration tests")
    return settings


@pytest.mark.integration
async def test_postgres_checkpoint_survives_new_workflow_service_instance() -> None:
    settings = _database_settings()
    actor_id = uuid4()
    order = OrderRead(
        id=uuid4(),
        customer_id=actor_id,
        status=OrderStatus.DELIVERED,
        total_amount=Decimal("12.50"),
    )
    policy = PolicyDocumentRead(
        id=uuid4(),
        slug="refund-and-delivery",
        version="2026-07-30",
        title="Refund policy",
        content="Refunds are available for delivered orders.",
        content_hash="c" * 64,
    )
    repository = InMemorySupportRepository((order,), (policy,))
    dependencies = default_dependencies(repository, TraceRecorder(None))
    dsn = _psycopg_url(settings)

    async with AsyncPostgresSaver.from_conn_string(dsn) as first_checkpointer:
        await first_checkpointer.setup()
        first_service = WorkflowService(dependencies, checkpointer=first_checkpointer)
        paused = await first_service.start(
            WorkflowRequest(
                actor_id=actor_id,
                request_id="postgres-checkpoint-1",
                message=f"Please refund order {order.id}",
            )
        )

    assert paused.status == "awaiting_confirmation"
    assert (await repository.get_order(order.id)).status is OrderStatus.DELIVERED

    async with AsyncPostgresSaver.from_conn_string(dsn) as second_checkpointer:
        second_service = WorkflowService(dependencies, checkpointer=second_checkpointer)
        completed = await second_service.confirm(
            paused.workflow_id,
            actor_id,
            "postgres-checkpoint-1",
        )

    assert completed.status == "completed"
    assert (await repository.get_order(order.id)).status is OrderStatus.REFUNDED
