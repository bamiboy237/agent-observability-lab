from uuid import UUID, uuid4

from app.domain.support.schemas import (
    OrderRead,
    OrderStatus,
    PolicyDocumentRead,
    TicketCreate,
    TicketRead,
)


class InMemorySupportRepository:
    def __init__(
        self,
        orders: tuple[OrderRead, ...] = (),
        policies: tuple[PolicyDocumentRead, ...] = (),
    ) -> None:
        self.orders = {order.id: order for order in orders}
        self.tickets: dict[UUID, TicketRead] = {}
        self.policies = {(policy.slug, policy.version): policy for policy in policies}

    async def get_order(self, order_id: UUID) -> OrderRead | None:
        return self.orders.get(order_id)

    async def save_order(self, order: OrderRead) -> OrderRead | None:
        if order.id not in self.orders:
            return None
        self.orders[order.id] = order
        return order

    async def refund_order_if_delivered(
        self, order_id: UUID, customer_id: UUID
    ) -> OrderRead | None:
        order = self.orders.get(order_id)
        if order is None or order.customer_id != customer_id or order.status != "delivered":
            return None
        refunded = order.model_copy(update={"status": OrderStatus.REFUNDED})
        self.orders[order_id] = refunded
        return refunded

    async def create_ticket(self, ticket: TicketCreate) -> TicketRead:
        stored_ticket = TicketRead(id=uuid4(), **ticket.model_dump())
        self.tickets[stored_ticket.id] = stored_ticket
        return stored_ticket

    async def get_ticket(self, ticket_id: UUID) -> TicketRead | None:
        return self.tickets.get(ticket_id)

    async def get_policy(
        self,
        slug: str,
        version: str | None = None,
    ) -> PolicyDocumentRead | None:
        matching = [
            policy
            for (policy_slug, policy_version), policy in self.policies.items()
            if policy_slug == slug and (version is None or policy_version == version)
        ]
        if not matching:
            return None
        return max(matching, key=lambda policy: policy.version)
