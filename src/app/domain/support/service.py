"""Application services for the support domain."""

from uuid import UUID

from app.domain.support.errors import Forbidden, OrderNotFound
from app.domain.support.repository import SupportRepository
from app.domain.support.schemas import OrderRead


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
