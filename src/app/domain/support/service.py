"""Application services for the support domain."""

from uuid import UUID

from app.domain.support.errors import Forbidden, InvalidTransition, OrderNotFound
from app.domain.support.repository import SupportRepository
from app.domain.support.schemas import (
    CreateTicketCommand,
    OrderRead,
    OrderStatus,
    RefundCommand,
    TicketCreate,
    TicketRead,
)

REFUNDABLE_ORDER_STATUSES = frozenset({OrderStatus.DELIVERED})


class SupportService:
    """Boundary between API callers and support persistence."""

    def __init__(self, repository: SupportRepository) -> None:
        self._repository = repository

    async def get_order(self, order_id: UUID, actor_id: UUID) -> OrderRead:
        """Return one order only when the requesting actor owns it."""
        order = await self._repository.get_order(order_id)
        if order is None:
            raise OrderNotFound()
        if order.customer_id != actor_id:
            raise Forbidden()
        return order

    async def create_ticket(self, command: CreateTicketCommand) -> TicketRead:
        """Create an open ticket owned by the requesting actor."""
        if command.order_id is not None:
            await self.get_order(command.order_id, command.actor_id)

        return await self._repository.create_ticket(
            TicketCreate(
                customer_id=command.actor_id,
                order_id=command.order_id,
                subject=command.subject,
            )
        )

    async def request_refund(self, command: RefundCommand) -> OrderRead:
        """Refund an owned order only from an explicitly allowed state."""
        order = await self.get_order(command.order_id, command.actor_id)
        if order.status not in REFUNDABLE_ORDER_STATUSES:
            raise InvalidTransition()

        refunded_order = order.model_copy(update={"status": OrderStatus.REFUNDED})
        saved_order = await self._repository.save_order(refunded_order)
        if saved_order is None:
            raise OrderNotFound()
        return saved_order
