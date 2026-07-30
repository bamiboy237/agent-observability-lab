from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import get_session_factory
from app.domain.support.models import Customer, Order, Ticket
from app.domain.support.schemas import CustomerRead, OrderRead, TicketRead


@pytest.fixture(scope="module", autouse=True)
def apply_support_migration() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for support schema integration tests")
    command.upgrade(Config("alembic.ini"), "head")


@pytest.mark.integration
async def test_support_models_round_trip_as_public_schemas() -> None:
    customer_id = uuid4()
    order_id = uuid4()
    ticket_id = uuid4()
    customer = Customer(
        id=customer_id,
        name="Review Customer",
        email=f"review-{uuid4().hex}@example.com",
    )
    order = Order(
        id=order_id,
        customer_id=customer_id,
        status="processing",
        total_amount=Decimal("42.50"),
    )
    ticket = Ticket(
        id=ticket_id,
        customer_id=customer_id,
        order_id=order_id,
        subject="Where is my order?",
        status="open",
    )

    session_factory = get_session_factory()
    async with session_factory() as session:
        session.add_all([customer, order, ticket])
        await session.commit()

    async with session_factory() as session:
        saved_customer = await session.get(Customer, customer_id)
        saved_order = await session.get(Order, order_id)
        saved_ticket = await session.get(Ticket, ticket_id)

        assert CustomerRead.model_validate(saved_customer).email == customer.email
        assert OrderRead.model_validate(saved_order).total_amount == Decimal("42.50")
        assert TicketRead.model_validate(saved_ticket).order_id == order_id

        await session.execute(delete(Ticket).where(Ticket.id == ticket_id))
        await session.execute(delete(Order).where(Order.id == order_id))
        await session.execute(delete(Customer).where(Customer.id == customer_id))
        await session.commit()


@pytest.mark.integration
async def test_order_customer_foreign_key_is_enforced() -> None:
    invalid_order = Order(
        customer_id=uuid4(),
        status="pending",
        total_amount=Decimal("10.00"),
    )

    async with get_session_factory()() as session:
        session.add(invalid_order)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
