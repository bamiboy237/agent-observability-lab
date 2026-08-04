"""Persistence boundary for the support domain."""

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.support.models import Order, Ticket
from app.domain.support.schemas import OrderRead, TicketCreate, TicketRead


class SupportRepository(Protocol):
    async def get_order(self, order_id: UUID) -> OrderRead | None: ...

    async def save_order(self, order: OrderRead) -> OrderRead | None: ...

    async def create_ticket(self, ticket: TicketCreate) -> TicketRead: ...

    async def get_ticket(self, ticket_id: UUID) -> TicketRead | None: ...


class SqlAlchemySupportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_order(self, order_id: UUID) -> OrderRead | None:
        order = await self._session.get(Order, order_id)
        return OrderRead.model_validate(order) if order is not None else None

    async def save_order(self, order: OrderRead) -> OrderRead | None:
        stored_order = await self._session.get(Order, order.id)
        if stored_order is None:
            return None

        stored_order.customer_id = order.customer_id
        stored_order.status = order.status
        stored_order.total_amount = order.total_amount
        await self._session.flush()
        return OrderRead.model_validate(stored_order)

    async def create_ticket(self, ticket: TicketCreate) -> TicketRead:
        stored_ticket = Ticket(**ticket.model_dump())
        self._session.add(stored_ticket)
        await self._session.flush()
        return TicketRead.model_validate(stored_ticket)

    async def get_ticket(self, ticket_id: UUID) -> TicketRead | None:
        ticket = await self._session.get(Ticket, ticket_id)
        return TicketRead.model_validate(ticket) if ticket is not None else None
