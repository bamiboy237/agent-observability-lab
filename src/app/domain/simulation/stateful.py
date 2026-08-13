"""This module implements the fast in-memory support test adapter.

This adapter is useful for focused unit tests. Full simulation runs use the
PostgreSQL sandbox so calls pass through the real application services and
repository.
"""

import copy
from uuid import UUID, uuid4

from app.domain.agent.instructions import ACCEPTED_POLICY_VERSION
from app.domain.simulation.adapters import (
    AdapterKind,
    DependencyCallResult,
    StateMutation,
)
from app.domain.simulation.errors import (
    UnsupportedArgumentsError,
    UnsupportedStateError,
    UnsupportedToolError,
)
from app.domain.simulation.schemas import SimulationState
from app.domain.support.schemas import (
    OrderRead,
    OrderStatus,
    PolicyDocumentRead,
    TicketRead,
    TicketStatus,
)
from app.domain.support.service import REFUNDABLE_ORDER_STATUSES

_REFUND_EXECUTED = "refund_executed"
_TICKET_CREATED = "ticket_created"


class StatefulSupportAdapter:
    """Simulate the support database and ticket store for unit tests.

    Reads answer from disposable state. Refunds require an eligible order
    and a proposal plus the trusted confirmation flag. Escalation creates a
    ticket. Every accepted mutation reports before/after state.
    """

    kind: AdapterKind = "stateful"
    dependency_name = "support.database"
    supported_tool_names = (
        "get_order_status",
        "get_policy",
        "propose_refund",
        "confirm_refund",
        "escalate",
    )

    def __init__(self, refund_confirmed: bool = False) -> None:
        self._refund_confirmed = refund_confirmed
        self._orders: dict[UUID, OrderRead] = {}
        self._tickets: dict[UUID, TicketRead] = {}
        self._policies: tuple[PolicyDocumentRead, ...] = ()
        self._proposals: set[UUID] = set()
        self._mutations: list[StateMutation] = []
        self._sequence = 0
        self._initial: SimulationState | None = None

    def supported_tools(self) -> tuple[str, ...]:
        return self.supported_tool_names

    def state_transitions(self) -> tuple[str, ...]:
        return ("order:delivered->refunded", "ticket:created")

    async def sanitize(self, captured: object) -> None:
        """Stateful adapters take approved seeds, not captured responses."""
        return None

    async def seed(self, state: SimulationState) -> None:
        """This method copies the approved state into disposable memory."""
        self._initial = state.model_copy(deep=True)
        self._orders = {order.id: order for order in state.orders}
        self._tickets = {ticket.id: ticket for ticket in state.tickets}
        self._policies = state.policies
        self._proposals = set()
        self._mutations = []
        self._sequence = 0

    async def reset(self) -> None:
        """This method restores the exact initial state snapshot."""
        if self._initial is None:
            return
        state = copy.deepcopy(self._initial)
        self._orders = {order.id: order for order in state.orders}
        self._tickets = {ticket.id: ticket for ticket in state.tickets}
        self._policies = state.policies
        self._proposals = set()
        self._mutations = []
        self._sequence = 0

    def mutations(self) -> tuple[StateMutation, ...]:
        return tuple(self._mutations)

    def _record(
        self,
        *,
        resource: str,
        resource_id: UUID,
        field: str,
        before: object | None,
        after: object | None,
        reason_code: str,
    ) -> StateMutation:
        self._sequence += 1
        mutation = StateMutation(
            sequence=self._sequence,
            resource=resource,
            resource_id=str(resource_id),
            field=field,
            before=before,
            after=after,
            reason_code=reason_code,
        )
        self._mutations.append(mutation)
        return mutation

    def _require_seeded(self) -> None:
        if self._initial is None:
            raise UnsupportedStateError(
                dependency=self.dependency_name,
                detail="no scenario state was seeded before the first call",
            )

    def _order_argument(self, tool_name: str, arguments: object) -> UUID:
        if not isinstance(arguments, dict):
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=arguments,
            )
        raw = arguments.get("order_id")
        try:
            return UUID(str(raw))
        except (TypeError, ValueError) as error:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=arguments,
            ) from error

    def _subject_argument(self, tool_name: str, arguments: object) -> str:
        if not isinstance(arguments, dict):
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=arguments,
            )
        subject = arguments.get("subject")
        if not isinstance(subject, str) or not subject:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=arguments,
            )
        return subject

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, object],
    ) -> DependencyCallResult:
        """This method handles one simulated support dependency call."""
        if tool_name not in self.supported_tool_names:
            raise UnsupportedToolError(dependency=self.dependency_name, tool=tool_name)
        self._require_seeded()
        if tool_name == "get_order_status":
            return await self._get_order_status(arguments)
        if tool_name == "get_policy":
            return await self._get_policy(arguments)
        if tool_name == "propose_refund":
            return await self._propose_refund(arguments)
        if tool_name == "confirm_refund":
            return await self._confirm_refund(arguments)
        return await self._escalate(arguments)

    async def _get_order_status(self, arguments: dict[str, object]) -> DependencyCallResult:
        order_id = self._order_argument("get_order_status", arguments)
        order = self._orders.get(order_id)
        if order is None:
            return DependencyCallResult(ok=False, error_code="order_not_found")
        return DependencyCallResult(ok=True, payload=order.model_dump(mode="json"))

    async def _get_policy(self, arguments: dict[str, object]) -> DependencyCallResult:
        if set(arguments) - {"slug"}:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool="get_policy",
                arguments=arguments,
            )
        slug = arguments.get("slug", "refund-and-delivery")
        if not isinstance(slug, str) or not slug:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool="get_policy",
                arguments=arguments,
            )
        policies = [policy for policy in self._policies if policy.slug == slug]
        if not policies:
            return DependencyCallResult(ok=False, error_code="policy_not_found")
        policy = max(policies, key=lambda item: item.version)
        return DependencyCallResult(ok=True, payload=policy.model_dump(mode="json"))

    async def _propose_refund(self, arguments: dict[str, object]) -> DependencyCallResult:
        order_id = self._order_argument("propose_refund", arguments)
        order = self._orders.get(order_id)
        if order is None:
            return DependencyCallResult(ok=False, error_code="order_not_found")
        if order.status not in REFUNDABLE_ORDER_STATUSES:
            return DependencyCallResult(ok=False, error_code="invalid_transition")
        self._proposals.add(order_id)
        return DependencyCallResult(
            ok=True,
            payload={
                "order_id": str(order.id),
                "amount": str(order.total_amount),
                "policy_version": ACCEPTED_POLICY_VERSION,
            },
        )

    async def _confirm_refund(self, arguments: dict[str, object]) -> DependencyCallResult:
        order_id = self._order_argument("confirm_refund", arguments)
        order = self._orders.get(order_id)
        if order is None:
            return DependencyCallResult(ok=False, error_code="order_not_found")
        if order_id not in self._proposals or not self._refund_confirmed:
            return DependencyCallResult(ok=False, error_code="refund_not_confirmed")
        refunded = order.model_copy(update={"status": OrderStatus.REFUNDED})
        self._orders[order_id] = refunded
        self._record(
            resource="order",
            resource_id=order_id,
            field="status",
            before=order.status.value,
            after=OrderStatus.REFUNDED.value,
            reason_code=_REFUND_EXECUTED,
        )
        return DependencyCallResult(ok=True, payload=refunded.model_dump(mode="json"))

    async def _escalate(self, arguments: dict[str, object]) -> DependencyCallResult:
        subject = self._subject_argument("escalate", arguments)
        ticket = TicketRead(
            id=uuid4(),
            customer_id=UUID(int=0),
            order_id=None,
            subject=subject,
            status=TicketStatus.OPEN,
        )
        self._tickets[ticket.id] = ticket
        self._record(
            resource="ticket",
            resource_id=ticket.id,
            field="created",
            before=None,
            after=ticket.model_dump(mode="json"),
            reason_code=_TICKET_CREATED,
        )
        return DependencyCallResult(ok=True, payload=ticket.model_dump(mode="json"))
