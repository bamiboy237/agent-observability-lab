from decimal import Decimal
from uuid import uuid4

from app.domain.support.schemas import (
    CreateTicketCommand,
    OrderRead,
    OrderStatus,
    TicketStatus,
)
from app.domain.support.service import SupportService
from tests.fakes.support_repository import InMemorySupportRepository


async def test_create_ticket_uses_actor_as_owner() -> None:
    actor_id = uuid4()
    order = OrderRead(
        id=uuid4(),
        customer_id=actor_id,
        status=OrderStatus.SHIPPED,
        total_amount=Decimal("135.00"),
    )
    repository = InMemorySupportRepository((order,))
    service = SupportService(repository)

    ticket = await service.create_ticket(
        CreateTicketCommand(
            actor_id=actor_id,
            order_id=order.id,
            subject="Where is my order?",
        )
    )

    assert ticket.customer_id == actor_id
    assert ticket.order_id == order.id
    assert ticket.status is TicketStatus.OPEN
    assert await repository.get_ticket(ticket.id) == ticket
