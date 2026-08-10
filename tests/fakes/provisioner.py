"""Fast in-memory provisioner for simulation runner unit tests.

This provisioner substitutes for the PostgreSQL sandbox the same way the
stateful support adapter substitutes for the database in Phase 4 unit tests:
it runs the same contract (create, seed, connect, retain, destroy, final
state, mutations) against an in-memory repository so runner tests stay fast
and offline. Full runs use the PostgreSQL provisioner.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.domain.simulation.adapters import AdapterKind, StateMutation
from app.domain.simulation.errors import EnvironmentRunError, SimulationError
from app.domain.simulation.events import SimulationEventKind, SimulationEventSink
from app.domain.simulation.faults import FaultInjectingRepository, FaultScript
from app.domain.simulation.postgres import ObservedSupportRepository
from app.domain.simulation.provisioner import (
    EnvironmentRequest,
    ProvisionerFactory,
    RetentionInfo,
    RetentionRequest,
    SupportEnvironmentProvisioner,
    mutation_event_attributes,
)
from app.domain.simulation.schemas import SimulationScenario, SimulationState
from app.domain.support.repository import SupportRepository
from tests.fakes.support_repository import InMemorySupportRepository


class StatefulSupportProvisioner:
    """This class provides the in-memory substitute provisioner for tests."""

    dependency_name = "support.database"
    kind: AdapterKind = "stateful"

    def __init__(
        self,
        scenario: SimulationScenario,
        *,
        fault_script: FaultScript | None = None,
        event_sink: SimulationEventSink | None = None,
        boundary_error: SimulationError | None = None,
    ) -> None:
        self.environment_id = uuid4().hex
        self._scenario = scenario
        self._fault_script = fault_script
        self._sink = event_sink
        self._boundary_error = boundary_error
        self._repository: InMemorySupportRepository | None = None
        self._observed: ObservedSupportRepository | None = None
        self._created = False
        self._destroyed = False
        self._retention: RetentionInfo | None = None
        self._initial: SimulationState | None = None

    @property
    def created(self) -> bool:
        return self._created

    @property
    def destroyed(self) -> bool:
        return self._destroyed

    async def create(self) -> None:
        self._created = True
        self._emit(SimulationEventKind.ENVIRONMENT_CREATED, {"environment.id": self.environment_id})

    async def seed(self, state: object) -> None:
        if not isinstance(state, SimulationState):
            raise ValueError("the seed must be a SimulationState")
        self._initial = state.model_copy(deep=True)
        repository = InMemorySupportRepository(
            orders=state.orders,
            policies=state.policies,
        )
        repository.tickets = {ticket.id: ticket for ticket in state.tickets}
        self._repository = repository
        self._observed = ObservedSupportRepository(
            repository,
            mutation_listener=self._on_mutation,
        )
        self._emit(
            SimulationEventKind.ENVIRONMENT_SEEDED,
            {
                "environment.id": self.environment_id,
                "seed.customers": len({order.customer_id for order in state.orders})
                + len({ticket.customer_id for ticket in state.tickets}),
                "seed.orders": len(state.orders),
                "seed.tickets": len(state.tickets),
                "seed.policies": len(state.policies),
            },
        )

    def connect(self) -> SupportRepository:
        if self._observed is None:
            raise RuntimeError("environment was not seeded")
        repository: SupportRepository = self._observed
        if self._fault_script is not None and self._fault_script.entries:
            if self._fault_script.dependency != self.dependency_name:
                raise EnvironmentRunError(
                    detail=(
                        f"fault script targets dependency "
                        f"{self._fault_script.dependency!r}, but this environment "
                        f"is {self.dependency_name!r}; a fault script may only "
                        "wrap the boundary that receives it"
                    )
                )
            repository = FaultInjectingRepository(
                self._observed,
                self._fault_script,
                event_sink=self._sink,
            )
        if self._boundary_error is not None:
            repository = _RejectingRepository(self._observed, self._boundary_error)
        return repository

    def retain(self, request: RetentionRequest) -> RetentionInfo:
        retained_at = datetime.now(UTC)
        info = RetentionInfo(
            environment_id=self.environment_id,
            reason=request.reason,
            retained_at=retained_at.isoformat(),
            expires_at=(retained_at + timedelta(hours=request.ttl_hours)).isoformat(),
        )
        self._retention = info
        self._emit(
            SimulationEventKind.ENVIRONMENT_RETAINED,
            {
                "environment.id": self.environment_id,
                "environment.retention.reason": info.reason,
                "environment.retention.expires_at": info.expires_at,
            },
        )
        return info

    @property
    def retention(self) -> RetentionInfo | None:
        return self._retention

    async def destroy(self) -> None:
        self._destroyed = True
        self._emit(
            SimulationEventKind.ENVIRONMENT_DESTROYED,
            {"environment.id": self.environment_id},
        )

    async def final_state(self) -> SimulationState:
        if self._repository is None:
            raise RuntimeError("environment was not seeded")
        return SimulationState(
            orders=tuple(self._repository.orders.values()),
            tickets=tuple(self._repository.tickets.values()),
            policies=tuple(self._repository.policies.values()),
        )

    def mutations(self) -> tuple[StateMutation, ...]:
        if self._observed is None:
            return ()
        return self._observed.mutations()

    def supported_tools(self) -> tuple[str, ...]:
        return (
            "get_order_status",
            "get_policy",
            "propose_refund",
            "confirm_refund",
            "escalate",
        )

    def state_transitions(self) -> tuple[str, ...]:
        return ("order:delivered->refunded", "ticket:created")

    async def sanitize(self, captured: object) -> None:
        return None

    async def reset(self) -> None:
        if self._initial is not None:
            await self.seed(self._initial)

    def _emit(self, kind: SimulationEventKind, attributes: dict[str, object]) -> None:
        if self._sink is not None:
            self._sink.emit(kind, attributes)

    def _on_mutation(self, mutation: StateMutation) -> None:
        if self._sink is not None:
            self._sink.emit(SimulationEventKind.STATE_MUTATION, mutation_event_attributes(mutation))


class _RejectingRepository:
    """This class rejects every access to simulate a failing boundary."""

    def __init__(
        self,
        repository: SupportRepository,
        error: SimulationError,
    ) -> None:
        self._repository = repository
        self._error = error

    async def get_order(self, order_id: UUID) -> object:
        raise self._error

    async def save_order(self, order: object) -> object:
        raise self._error

    async def create_ticket(self, ticket: object) -> object:
        raise self._error

    async def get_ticket(self, ticket_id: UUID) -> object:
        raise self._error

    async def get_policy(self, slug: str, version: str | None = None) -> object:
        raise self._error


def stateful_provisioner_factory(
    *,
    boundary_error: SimulationError | None = None,
) -> ProvisionerFactory:
    """This function builds a factory for the in-memory test provisioner."""

    def build(request: EnvironmentRequest) -> SupportEnvironmentProvisioner:
        return StatefulSupportProvisioner(
            request.scenario,
            fault_script=request.fault_script,
            event_sink=request.sink,
            boundary_error=boundary_error,
        )

    return build


async def drain(collector) -> None:
    """This function waits for pending subscriber events in tests."""
    await asyncio.sleep(0)
