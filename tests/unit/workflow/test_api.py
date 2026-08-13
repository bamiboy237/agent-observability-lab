"""HTTP boundary tests for workflow IDs and confirmation bindings."""

from decimal import Decimal
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.workflow_router import _psycopg_url, get_workflow_service, router
from app.config import Settings
from app.domain.support.schemas import OrderRead, OrderStatus, PolicyDocumentRead
from app.domain.workflow.service import WorkflowService, default_dependencies
from app.telemetry.recorder import TraceRecorder
from tests.fakes.support_repository import InMemorySupportRepository


def make_client() -> tuple[TestClient, InMemorySupportRepository, object, object]:
    actor_id = uuid4()
    order = OrderRead(
        id=uuid4(),
        customer_id=actor_id,
        status=OrderStatus.DELIVERED,
        total_amount=Decimal("18.00"),
    )
    policy = PolicyDocumentRead(
        id=uuid4(),
        slug="refund-and-delivery",
        version="2026-07-30",
        title="Refund policy",
        content="Refunds are available.",
        content_hash="b" * 64,
    )
    repository = InMemorySupportRepository((order,), (policy,))
    service = WorkflowService(default_dependencies(repository, TraceRecorder(None)))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_workflow_service] = lambda: service
    return TestClient(app), repository, actor_id, order


def test_workflow_api_returns_stable_ids_and_supports_confirm_without_message() -> None:
    client, repository, actor_id, order = make_client()
    start = client.post(
        "/workflows",
        json={
            "actor_id": str(actor_id),
            "request_id": "api-refund-1",
            "message": f"Please refund {order.id}",
        },
    )
    assert start.status_code == 200
    payload = start.json()
    assert payload["status"] == "awaiting_confirmation"
    assert payload["interrupted"] is True
    workflow_id = payload["workflow_id"]
    assert payload["run_id"]

    confirm = client.post(
        f"/workflows/{workflow_id}/confirm",
        json={"actor_id": str(actor_id), "request_id": "api-refund-1"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "completed"
    assert repository.orders[order.id].status is OrderStatus.REFUNDED


def test_checkpoint_url_uses_psycopg_scheme_without_logging_or_asyncpg_options() -> None:
    database_url = (
        "postgresql://user:password@example.test:5432/lab?"
        "sslmode=require&channel_binding=require"
    )
    settings = Settings(
        database_url=database_url,
        database_url_unpooled=database_url,
        _env_file=None,
    )

    url = _psycopg_url(settings)

    assert url.startswith("postgresql://user:password@example.test:5432/lab")
    assert "sslmode=require" in url
    assert "channel_binding" not in url
    assert "postgresql+asyncpg" not in url
