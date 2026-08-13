import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import delete

from app.config import Settings
from app.db import get_session_factory
from app.domain.support.models import Customer, Order, Ticket
from app.domain.support.repository import SqlAlchemySupportRepository
from app.domain.support.schemas import OrderStatus, RefundCommand, TicketCreate
from app.domain.support.service import SupportService


@pytest.fixture(scope="module", autouse=True)
def apply_repository_migrations() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for repository integration tests")
    command.upgrade(Config("alembic.ini"), "head")


@pytest.mark.integration
async def test_postgres_repository_contract_and_commit_visibility() -> None:
    customer_id = uuid4()
    order_id = uuid4()
    customer = Customer(
        id=customer_id,
        name="Repository Customer",
        email=f"repository-{uuid4().hex}@example.test",
    )
    order = Order(
        id=order_id,
        customer_id=customer_id,
        status="pending",
        total_amount=Decimal("25.00"),
    )

    async with get_session_factory().begin() as session:
        session.add_all([customer, order])

    async with get_session_factory().begin() as session:
        repository = SqlAlchemySupportRepository(session)
        assert await repository.get_order(uuid4()) is None

        saved_order = await repository.get_order(order_id)
        assert saved_order is not None
        updated_order = saved_order.model_copy(update={"status": OrderStatus.PROCESSING})
        assert await repository.save_order(updated_order) == updated_order

        ticket = await repository.create_ticket(
            TicketCreate(
                customer_id=customer_id,
                order_id=order_id,
                subject="Where is my order?",
            )
        )
        ticket_id = ticket.id

    async with get_session_factory().begin() as session:
        repository = SqlAlchemySupportRepository(session)
        committed_order = await repository.get_order(order_id)
        committed_ticket = await repository.get_ticket(ticket_id)

        assert committed_order is not None
        assert committed_order.status is OrderStatus.PROCESSING
        assert committed_ticket == ticket
        assert await repository.get_ticket(uuid4()) is None

        await session.execute(delete(Ticket).where(Ticket.id == ticket_id))
        await session.execute(delete(Order).where(Order.id == order_id))
        await session.execute(delete(Customer).where(Customer.id == customer_id))


@pytest.mark.integration
async def test_concurrent_refunds_allow_exactly_one_state_transition() -> None:
    customer_id = uuid4()
    order_id = uuid4()
    async with get_session_factory().begin() as session:
        session.add(
            Customer(
                id=customer_id,
                name="Concurrent Refund Customer",
                email=f"refund-{uuid4().hex}@example.test",
            )
        )
        session.add(
            Order(
                id=order_id,
                customer_id=customer_id,
                status="delivered",
                total_amount=Decimal("48.25"),
            )
        )

    async def refund_once() -> object:
        try:
            async with get_session_factory().begin() as session:
                return await SupportService(
                    SqlAlchemySupportRepository(session)
                ).request_refund(RefundCommand(actor_id=customer_id, order_id=order_id))
        except Exception as error:  # outcome is asserted below
            return error

    outcomes = await asyncio.gather(refund_once(), refund_once())

    assert (
        sum(getattr(outcome, "status", None) is OrderStatus.REFUNDED for outcome in outcomes)
        == 1
    )
    assert sum(getattr(outcome, "code", None) == "invalid_transition" for outcome in outcomes) == 1

    async with get_session_factory().begin() as session:
        stored = await SqlAlchemySupportRepository(session).get_order(order_id)
        assert stored is not None
        assert stored.status is OrderStatus.REFUNDED
        await session.execute(delete(Order).where(Order.id == order_id))
        await session.execute(delete(Customer).where(Customer.id == customer_id))
