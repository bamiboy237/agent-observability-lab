from decimal import Decimal
from uuid import uuid4

from app.domain.support.repository import SupportRepository
from app.domain.support.schemas import OrderRead, OrderStatus, TicketCreate
from tests.fakes.support_repository import InMemorySupportRepository


async def test_in_memory_repository_matches_support_contract() -> None:
    customer_id = uuid4()
    order = OrderRead(
        id=uuid4(),
        customer_id=customer_id,
        status=OrderStatus.PENDING,
        total_amount=Decimal("25.00"),
    )
    repository: SupportRepository = InMemorySupportRepository((order,))

    assert await repository.get_order(uuid4()) is None
    assert await repository.save_order(order.model_copy(update={"id": uuid4()})) is None

    updated_order = order.model_copy(update={"status": OrderStatus.PROCESSING})
    assert await repository.save_order(updated_order) == updated_order
    assert await repository.get_order(order.id) == updated_order

    ticket = await repository.create_ticket(
        TicketCreate(customer_id=customer_id, order_id=order.id, subject="Order status")
    )
    assert await repository.get_ticket(ticket.id) == ticket
