from uuid import UUID, uuid4

from app.domain.support.schemas import OrderRead, TicketCreate, TicketRead


class InMemorySupportRepository:
    def __init__(self, orders: tuple[OrderRead, ...] = ()) -> None:
        self.orders = {order.id: order for order in orders}
        self.tickets: dict[UUID, TicketRead] = {}

    async def get_order(self, order_id: UUID) -> OrderRead | None:
        return self.orders.get(order_id)

    async def save_order(self, order: OrderRead) -> OrderRead | None:
        if order.id not in self.orders:
            return None
        self.orders[order.id] = order
        return order

    async def create_ticket(self, ticket: TicketCreate) -> TicketRead:
        stored_ticket = TicketRead(id=uuid4(), **ticket.model_dump())
        self.tickets[stored_ticket.id] = stored_ticket
        return stored_ticket

    async def get_ticket(self, ticket_id: UUID) -> TicketRead | None:
        return self.tickets.get(ticket_id)
