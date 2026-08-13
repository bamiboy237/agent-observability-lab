from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.domain.support.errors import Forbidden, InvalidTransition, OrderNotFound
from app.domain.support.schemas import OrderRead, OrderStatus, RefundCommand
from app.domain.support.service import SupportService
from tests.fakes.support_repository import InMemorySupportRepository


def make_order(status: OrderStatus = OrderStatus.DELIVERED) -> OrderRead:
    return OrderRead(
        id=uuid4(),
        customer_id=uuid4(),
        status=status,
        total_amount=Decimal("48.25"),
    )


async def test_delivered_order_can_be_refunded() -> None:
    order = make_order()
    repository = InMemorySupportRepository((order,))
    service = SupportService(repository)

    refunded = await service.request_refund(
        RefundCommand(actor_id=order.customer_id, order_id=order.id)
    )

    assert refunded.status is OrderStatus.REFUNDED
    assert await repository.get_order(order.id) == refunded


async def test_missing_order_cannot_be_refunded() -> None:
    service = SupportService(InMemorySupportRepository())

    with pytest.raises(OrderNotFound):
        await service.request_refund(RefundCommand(actor_id=uuid4(), order_id=uuid4()))


async def test_another_customer_cannot_refund_order() -> None:
    order = make_order()
    service = SupportService(InMemorySupportRepository((order,)))

    with pytest.raises(Forbidden):
        await service.request_refund(RefundCommand(actor_id=uuid4(), order_id=order.id))


@pytest.mark.parametrize(
    "status",
    [status for status in OrderStatus if status is not OrderStatus.DELIVERED],
)
async def test_disallowed_order_status_remains_unchanged(status: OrderStatus) -> None:
    order = make_order(status)
    repository = InMemorySupportRepository((order,))
    service = SupportService(repository)

    with pytest.raises(InvalidTransition) as error:
        await service.request_refund(RefundCommand(actor_id=order.customer_id, order_id=order.id))

    assert error.value.code == "invalid_transition"
    assert error.value.status_code == 409
    assert await repository.get_order(order.id) == order


async def test_repository_failure_leaves_order_unchanged() -> None:
    order = make_order()

    class FailingRepository(InMemorySupportRepository):
        async def refund_order_if_delivered(
            self, order_id: UUID, customer_id: UUID
        ) -> OrderRead | None:
            raise RuntimeError("database write failed")

    repository = FailingRepository((order,))
    service = SupportService(repository)

    with pytest.raises(RuntimeError, match="database write failed"):
        await service.request_refund(RefundCommand(actor_id=order.customer_id, order_id=order.id))

    assert await repository.get_order(order.id) == order
