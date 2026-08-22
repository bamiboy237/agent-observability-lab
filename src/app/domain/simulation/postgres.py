"""Run support scenarios through the real application code and PostgreSQL."""

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agent.errors import AgentError
from app.domain.agent.service import SupportAgentService
from app.domain.simulation.adapters import AdapterKind, DependencyCallResult, StateMutation
from app.domain.simulation.errors import (
    UnsupportedArgumentsError,
    UnsupportedStateError,
    UnsupportedToolError,
)
from app.domain.simulation.schemas import SimulationScenario, SimulationState
from app.domain.support.errors import SupportError
from app.domain.support.models import Customer, Order, PolicyDocument, Ticket
from app.domain.support.repository import SqlAlchemySupportRepository, SupportRepository
from app.domain.support.schemas import OrderRead, PolicyDocumentRead, TicketCreate, TicketRead
from app.domain.support.service import SupportService
from app.telemetry.recorder import TraceRecorder

_REFUND_EXECUTED = "refund_executed"
_TICKET_CREATED = "ticket_created"

_TEMPORARY_SUPPORT_TABLES = (
    """
    CREATE TEMPORARY TABLE customers (
        id UUID PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        email VARCHAR(320) NOT NULL UNIQUE
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMPORARY TABLE orders (
        id UUID PRIMARY KEY,
        customer_id UUID NOT NULL REFERENCES customers(id),
        status VARCHAR(20) NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'processing', 'shipped', 'delivered',
                              'cancelled', 'refunded')),
        total_amount NUMERIC(12, 2) NOT NULL CHECK (total_amount >= 0)
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMPORARY TABLE tickets (
        id UUID PRIMARY KEY,
        customer_id UUID NOT NULL REFERENCES customers(id),
        order_id UUID REFERENCES orders(id),
        subject VARCHAR(300) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'open'
            CHECK (status IN ('open', 'in_progress', 'resolved', 'closed'))
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMPORARY TABLE policy_documents (
        id UUID PRIMARY KEY,
        slug VARCHAR(100) NOT NULL,
        version VARCHAR(20) NOT NULL,
        title VARCHAR(200) NOT NULL,
        content TEXT NOT NULL,
        content_hash VARCHAR(64) NOT NULL,
        UNIQUE (slug, version)
    ) ON COMMIT DROP
    """,
)


@dataclass(frozen=True)
class PostgresSandboxTarget:
    """Identify the approved test database that a sandbox may replace."""

    host: str
    port: int
    database: str
    role: str

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
        *,
        environment: str = "test",
    ) -> "PostgresSandboxTarget":
        """Build a target from a PostgreSQL database URL."""
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql":
            raise ValueError("PostgreSQL sandbox provisioning requires a PostgreSQL URL")
        if not url.host or not url.database or not url.username:
            raise ValueError("PostgreSQL sandbox URL must include host, database, and role")
        return cls(
            host=url.host.casefold(),
            port=url.port or 5432,
            database=url.database,
            role=url.username,
        )


class ObservedSupportRepository:
    """Delegate to the real repository and report accepted database writes.

    An optional mutation listener observes every accepted mutation as it is
    recorded, so simulation runs can stream state changes while the agent
    executes. Without a listener the behavior is unchanged.
    """

    def __init__(
        self,
        repository: SupportRepository,
        mutation_listener: Callable[[StateMutation], None] | None = None,
    ) -> None:
        self._repository = repository
        self._mutations: list[StateMutation] = []
        self._sequence = 0
        self._listener = mutation_listener

    async def get_order(self, order_id: UUID) -> OrderRead | None:
        return await self._repository.get_order(order_id)

    async def save_order(self, order: OrderRead) -> OrderRead | None:
        before = await self._repository.get_order(order.id)
        saved = await self._repository.save_order(order)
        if before is not None and saved is not None and before.status != saved.status:
            self._record(
                resource="order",
                resource_id=saved.id,
                field="status",
                before=before.status.value,
                after=saved.status.value,
                reason_code=_REFUND_EXECUTED,
            )
        return saved

    async def refund_order_if_delivered(
        self, order_id: UUID, customer_id: UUID
    ) -> OrderRead | None:
        before = await self._repository.get_order(order_id)
        saved = await self._repository.refund_order_if_delivered(order_id, customer_id)
        if before is not None and saved is not None and before.status != saved.status:
            self._record(
                resource="order",
                resource_id=saved.id,
                field="status",
                before=before.status.value,
                after=saved.status.value,
                reason_code=_REFUND_EXECUTED,
            )
        return saved

    async def create_ticket(self, ticket: TicketCreate) -> TicketRead:
        created = await self._repository.create_ticket(ticket)
        self._record(
            resource="ticket",
            resource_id=created.id,
            field="created",
            before=None,
            after=created.model_dump(mode="json"),
            reason_code=_TICKET_CREATED,
        )
        return created

    async def get_ticket(self, ticket_id: UUID) -> TicketRead | None:
        return await self._repository.get_ticket(ticket_id)

    async def get_policy(
        self,
        slug: str,
        version: str | None = None,
    ) -> PolicyDocumentRead | None:
        return await self._repository.get_policy(slug, version)

    def mutations(self) -> tuple[StateMutation, ...]:
        return tuple(self._mutations)

    def clear_mutations(self) -> None:
        self._mutations = []
        self._sequence = 0

    def _record(
        self,
        *,
        resource: str,
        resource_id: UUID,
        field: str,
        before: object | None,
        after: object | None,
        reason_code: str,
    ) -> None:
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
        if self._listener is not None:
            self._listener(mutation)


class PostgresSupportSandbox:
    """Run one scenario through real support services and an isolated database.

    The caller must provide a disposable PostgreSQL database or an open
    transaction that it will roll back. This class never commits.
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

    def __init__(
        self,
        session: AsyncSession,
        scenario: SimulationScenario,
        *,
        isolation_confirmed: bool,
        target: PostgresSandboxTarget,
        mutation_listener: Callable[[StateMutation], None] | None = None,
    ) -> None:
        if not isolation_confirmed:
            raise ValueError("PostgreSQL sandbox seeding requires an isolated database")
        self._session = session
        self._scenario = scenario
        self._target = target
        self._target_verified = False
        self._temporary_tables_ready = False
        self._initial: SimulationState | None = None
        self._observed_repository = ObservedSupportRepository(
            SqlAlchemySupportRepository(session),
            mutation_listener=mutation_listener,
        )
        self._agent_service: SupportAgentService | None = None

    @property
    def repository(self) -> SupportRepository:
        """Return the real SQL repository path for a hosted-model agent."""
        return self._observed_repository

    def supported_tools(self) -> tuple[str, ...]:
        return self.supported_tool_names

    def state_transitions(self) -> tuple[str, ...]:
        return ("order:delivered->refunded", "ticket:created")

    async def sanitize(self, captured: Mapping[str, object]) -> None:
        """Accept no captured payloads; PostgreSQL state comes from the scenario."""
        if captured:
            raise UnsupportedStateError(
                dependency=self.dependency_name,
                detail="captured responses belong in a recorded external adapter",
            )

    async def seed(self, state: object) -> None:
        """Load approved scenario state into the isolated PostgreSQL database."""
        if not isinstance(state, SimulationState):
            raise UnsupportedStateError(
                dependency=self.dependency_name,
                detail="the seed must be a SimulationState",
            )
        await self.verify_target()
        self._initial = state.model_copy(deep=True)
        await self._replace_database_state(self._initial)

    async def verify_target(self) -> None:
        """Verify that the database session is active and reachable."""
        if self._target_verified:
            return
        await self._session.execute(text("SELECT 1"))
        await self._prepare_temporary_tables()
        self._target_verified = True

    async def _prepare_temporary_tables(self) -> None:
        """Create session-local support tables and forbid public-table fallback."""
        if self._temporary_tables_ready:
            return
        for statement in _TEMPORARY_SUPPORT_TABLES:
            await self._session.execute(text(statement))
        await self._session.execute(text("SET LOCAL search_path TO pg_temp"))
        self._temporary_tables_ready = True

    async def reset(self) -> None:
        """Restore the exact approved state in the isolated PostgreSQL database."""
        if self._initial is None:
            return
        await self._replace_database_state(copy.deepcopy(self._initial))

    def mutations(self) -> tuple[StateMutation, ...]:
        return self._observed_repository.mutations()

    async def call(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> DependencyCallResult:
        """Call one real support tool against isolated PostgreSQL state."""
        if tool_name not in self.supported_tool_names:
            raise UnsupportedToolError(dependency=self.dependency_name, tool=tool_name)
        service = self._require_seeded()
        try:
            if tool_name == "get_order_status":
                self._require_exact_arguments(tool_name, arguments, {"order_id"})
                return self._success(
                    await service.get_order_status(
                        self._uuid_argument(tool_name, arguments, "order_id")
                    )
                )
            if tool_name == "get_policy":
                self._require_exact_arguments(tool_name, arguments, {"slug"}, optional={"slug"})
                return self._success(
                    await service.get_policy(
                        self._optional_string_argument(tool_name, arguments, "slug")
                        or "refund-and-delivery"
                    )
                )
            if tool_name == "propose_refund":
                self._require_exact_arguments(tool_name, arguments, {"order_id", "reason"})
                return self._success(
                    await service.propose_refund(
                        self._uuid_argument(tool_name, arguments, "order_id"),
                        self._required_string_argument(tool_name, arguments, "reason"),
                    )
                )
            if tool_name == "confirm_refund":
                self._require_exact_arguments(tool_name, arguments, {"order_id"})
                return self._success(
                    await service.confirm_refund(
                        self._uuid_argument(tool_name, arguments, "order_id")
                    )
                )
            self._require_exact_arguments(tool_name, arguments, {"subject"})
            return self._success(
                await service.escalate(
                    self._required_string_argument(tool_name, arguments, "subject")
                )
            )
        except (AgentError, SupportError) as error:
            return DependencyCallResult(ok=False, error_code=error.code)

    def _success(self, result: BaseModel) -> DependencyCallResult:
        return DependencyCallResult(
            ok=True,
            payload=result.model_dump(mode="json"),
            mutations=self.mutations(),
        )

    def _require_seeded(self) -> SupportAgentService:
        if self._agent_service is None:
            raise UnsupportedStateError(
                dependency=self.dependency_name,
                detail="no scenario state was seeded before the first call",
            )
        return self._agent_service

    def _uuid_argument(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        name: str,
    ) -> UUID:
        try:
            return UUID(str(arguments[name]))
        except (KeyError, TypeError, ValueError) as error:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=arguments,
            ) from error

    def _required_string_argument(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        name: str,
    ) -> str:
        value = arguments.get(name)
        if not isinstance(value, str) or not value:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=arguments,
            )
        return value

    def _optional_string_argument(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        name: str,
    ) -> str | None:
        value = arguments.get(name)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=arguments,
            )
        return value

    def _require_exact_arguments(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        allowed: set[str],
        *,
        optional: set[str] | None = None,
    ) -> None:
        supplied = set(arguments)
        required = allowed - (optional or set())
        if supplied - allowed or required - supplied:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=arguments,
            )

    async def _replace_database_state(self, state: SimulationState) -> None:
        self._session.expunge_all()
        await self._session.execute(
            text("TRUNCATE TABLE tickets, orders, policy_documents, customers")
        )

        customer_ids = {self._scenario.request.customer_id}
        customer_ids.update(order.customer_id for order in state.orders)
        customer_ids.update(ticket.customer_id for ticket in state.tickets)
        for customer_id in sorted(customer_ids, key=str):
            self._session.add(
                Customer(
                    id=customer_id,
                    name=f"Sandbox customer {str(customer_id)[:8]}",
                    email=f"sandbox+{customer_id}@example.invalid",
                )
            )
        self._session.add_all(
            [
                Order(
                    id=order.id,
                    customer_id=order.customer_id,
                    status=order.status.value,
                    total_amount=order.total_amount,
                )
                for order in state.orders
            ]
        )
        self._session.add_all(
            [
                Ticket(
                    id=ticket.id,
                    customer_id=ticket.customer_id,
                    order_id=ticket.order_id,
                    subject=ticket.subject,
                    status=ticket.status.value,
                )
                for ticket in state.tickets
            ]
        )
        self._session.add_all(
            [
                PolicyDocument(
                    id=policy.id,
                    slug=policy.slug,
                    version=policy.version,
                    title=policy.title,
                    content=policy.content,
                    content_hash=policy.content_hash,
                )
                for policy in state.policies
            ]
        )
        await self._session.flush()
        self._observed_repository.clear_mutations()
        self._agent_service = SupportAgentService(
            SupportService(self._observed_repository),
            customer_id=self._scenario.request.customer_id,
            recorder=TraceRecorder(None),
            refund_confirmed=self._scenario.request.refund_confirmed,
        )
