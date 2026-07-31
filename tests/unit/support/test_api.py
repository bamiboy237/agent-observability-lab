from decimal import Decimal
from unittest.mock import AsyncMock, create_autospec
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.support_router import get_support_service
from app.config import Settings
from app.domain.support.errors import Forbidden, InvalidTransition, OrderNotFound
from app.domain.support.schemas import OrderRead, OrderStatus, TicketRead, TicketStatus
from app.domain.support.service import SupportService
from app.main import create_app


def make_client(service: SupportService) -> TestClient:
    app = create_app(
        Settings(
            database_url="postgresql://user:password@localhost:5432/app",
            environment="test",
            _env_file=None,
        )
    )
    app.dependency_overrides[get_support_service] = lambda: service
    return TestClient(app)


def make_service() -> SupportService:
    return create_autospec(SupportService, instance=True)


def test_order_lookup_route_returns_public_order() -> None:
    order = OrderRead(
        id=uuid4(),
        customer_id=uuid4(),
        status=OrderStatus.SHIPPED,
        total_amount=Decimal("135.00"),
    )
    service = make_service()
    service.get_order = AsyncMock(return_value=order)

    response = make_client(service).get(
        f"/support/orders/{order.id}",
        params={"actor_id": str(order.customer_id)},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(order.id)


def test_ticket_route_creates_open_ticket() -> None:
    ticket = TicketRead(
        id=uuid4(),
        customer_id=uuid4(),
        order_id=uuid4(),
        subject="Where is my order?",
        status=TicketStatus.OPEN,
    )
    service = make_service()
    service.create_ticket = AsyncMock(return_value=ticket)

    response = make_client(service).post(
        "/support/tickets",
        json={
            "actor_id": str(ticket.customer_id),
            "order_id": str(ticket.order_id),
            "subject": ticket.subject,
        },
    )

    assert response.status_code == 201
    assert response.json() == ticket.model_dump(mode="json")


def test_refund_route_returns_refunded_order() -> None:
    order = OrderRead(
        id=uuid4(),
        customer_id=uuid4(),
        status=OrderStatus.REFUNDED,
        total_amount=Decimal("48.25"),
    )
    service = make_service()
    service.request_refund = AsyncMock(return_value=order)

    response = make_client(service).post(
        "/support/refunds",
        json={"actor_id": str(order.customer_id), "order_id": str(order.id)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "refunded"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (OrderNotFound(), 404, "order_not_found"),
        (Forbidden(), 403, "forbidden"),
        (InvalidTransition(), 409, "invalid_transition"),
    ],
)
def test_support_routes_return_typed_errors(
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    service = make_service()
    service.request_refund = AsyncMock(side_effect=error)

    response = make_client(service).post(
        "/support/refunds",
        json={"actor_id": str(uuid4()), "order_id": str(uuid4())},
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
