import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, update

from app.config import Settings
from app.db import get_session_factory
from app.domain.support.models import Order, Ticket
from app.domain.support.schemas import OrderStatus
from app.domain.support.seed import CUSTOMERS, ORDERS, seed_support_data
from app.main import create_app


@pytest.fixture(scope="module", autouse=True)
def apply_support_api_migrations() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for support API integration tests")
    command.upgrade(Config("alembic.ini"), "head")


@pytest.mark.integration
async def test_support_api_happy_path_uses_postgres() -> None:
    async with get_session_factory().begin() as session:
        await seed_support_data(session)

    customer_id = CUSTOMERS[1]["id"]
    order_id = next(order["id"] for order in ORDERS if order["status"] == "delivered")
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        order_response = await client.get(
            f"/support/orders/{order_id}",
            params={"actor_id": str(customer_id)},
        )
        ticket_response = await client.post(
            "/support/tickets",
            json={
                "actor_id": str(customer_id),
                "order_id": str(order_id),
                "subject": "Please help with my delivered order",
            },
        )
        refund_response = await client.post(
            "/support/refunds",
            json={"actor_id": str(customer_id), "order_id": str(order_id)},
        )

    assert order_response.status_code == 200
    assert ticket_response.status_code == 201
    assert refund_response.status_code == 200
    assert refund_response.json()["status"] == "refunded"

    ticket_id = ticket_response.json()["id"]
    async with get_session_factory().begin() as session:
        await session.execute(delete(Ticket).where(Ticket.id == ticket_id))
        await session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(status=OrderStatus.DELIVERED)
        )
