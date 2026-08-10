"""This module defines the ephemeral environment provisioner contract.

A provisioner creates one disposable copy of the owned systems that a
simulation needs, seeds it from approved state, connects the real application
to it, and destroys or rolls it back. The reference implementation provisions
an isolated PostgreSQL environment that runs the
real support services, repository, validation, policy rules, and SQL inside
one transaction that the run rolls back.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction

from app.domain.simulation.adapters import AdapterKind, DependencyCallResult, StateMutation
from app.domain.simulation.errors import EnvironmentRunError
from app.domain.simulation.events import SimulationEventKind, SimulationEventSink
from app.domain.simulation.faults import FaultInjectingRepository, FaultScript
from app.domain.simulation.postgres import PostgresSandboxTarget, PostgresSupportSandbox
from app.domain.simulation.schemas import SimulationScenario, SimulationState
from app.domain.support.models import Order, PolicyDocument, Ticket
from app.domain.support.repository import SupportRepository
from app.domain.support.schemas import OrderRead, PolicyDocumentRead, TicketRead

SessionFactory = Callable[[], AsyncSession]
Scalar = bool | int | float | str


@runtime_checkable
class EnvironmentProvisioner(Protocol):
    """This protocol defines the minimum operations of every provisioner.

    ``create`` builds the isolated environment, ``seed`` loads the approved
    disposable state, ``connect`` returns the connected dependency handle,
    ``destroy`` tears the environment down or rolls it back. ``final_state``
    captures the disposable state after a run and ``mutations`` reports the
    accepted state mutations.
    """

    dependency_name: str
    environment_id: str

    async def create(self) -> None: ...

    async def seed(self, state: object) -> None: ...

    def connect(self) -> object: ...

    async def destroy(self) -> None: ...

    async def final_state(self) -> object: ...

    def mutations(self) -> tuple[StateMutation, ...]: ...


@runtime_checkable
class SupportEnvironmentProvisioner(EnvironmentProvisioner, Protocol):
    """This protocol narrows the provisioner for the support workflow."""

    def connect(self) -> SupportRepository: ...

    async def final_state(self) -> SimulationState: ...


@dataclass(frozen=True)
class EnvironmentRequest:
    """This class carries what a provisioner factory needs to build an environment.

    The runner reconstructs the scenario from the bundle, then asks the
    factory for a provisioner for that scenario with the bundle fault script
    and the run event sink.
    """

    scenario: SimulationScenario
    fault_script: FaultScript | None
    sink: SimulationEventSink


ProvisionerFactory = Callable[[EnvironmentRequest], SupportEnvironmentProvisioner]


def postgres_provisioner_factory(
    session_factory: SessionFactory,
    *,
    database_url: str,
    environment: str,
    isolation_confirmed: bool,
) -> ProvisionerFactory:
    """This function builds the reference PostgreSQL provisioner factory.

    Every run gets a fresh provisioner for its own scenario, fault script,
    and event sink, so runs never share a transaction or environment.
    """

    target = PostgresSandboxTarget.from_database_url(
        database_url,
        environment=environment,
    )

    def build(request: EnvironmentRequest) -> SupportEnvironmentProvisioner:
        return PostgresSandboxProvisioner(
            session_factory,
            request.scenario,
            isolation_confirmed=isolation_confirmed,
            target=target,
            fault_script=request.fault_script,
            event_sink=request.sink,
        )

    return build


def _scalar_or_none(value: object) -> str | None:
    """This function keeps short scalar values for the event transcript."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return str(value)
    if isinstance(value, str) and len(value) <= 100:
        return value
    return None


def mutation_event_attributes(mutation: StateMutation) -> dict[str, Scalar]:
    """This function maps one state mutation to allowlisted event attributes."""
    attributes: dict[str, Scalar] = {
        "mutation.resource": mutation.resource,
        "mutation.resource_id": mutation.resource_id,
        "mutation.field": mutation.field,
        "mutation.reason.code": mutation.reason_code,
    }
    before = _scalar_or_none(mutation.before)
    after = _scalar_or_none(mutation.after)
    if before is not None:
        attributes["mutation.before"] = before
    if after is not None:
        attributes["mutation.after"] = after
    return attributes


class PostgresSandboxProvisioner:
    """This class provisions one isolated PostgreSQL sandbox for a scenario.

    The environment is one transaction on a disposable PostgreSQL database.
    Seeding replaces the transaction's rows with the approved synthetic
    state, the agent runs against the real services and repository inside the
    transaction, and ``destroy`` rolls the transaction back so the database
    is unchanged.
    """

    dependency_name = "support.database"
    kind: AdapterKind = "stateful"

    def __init__(
        self,
        session_factory: SessionFactory,
        scenario: SimulationScenario,
        *,
        isolation_confirmed: bool,
        target: PostgresSandboxTarget,
        fault_script: FaultScript | None = None,
        event_sink: SimulationEventSink | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._scenario = scenario
        self._fault_script = fault_script
        self._sink = event_sink
        self._session: AsyncSession | None = None
        self._transaction: AsyncSessionTransaction | None = None
        self._sandbox: PostgresSupportSandbox | None = None
        self._target = target
        self.environment_id = uuid4().hex
        if not isolation_confirmed:
            raise ValueError("PostgreSQL sandbox provisioning requires an isolated database")

    async def create(self) -> None:
        """This method opens the disposable transaction and builds the sandbox."""
        if self._sandbox is not None:
            raise EnvironmentRunError(detail="environment is already created")
        session = self._session_factory()
        transaction = await session.begin()
        self._session = session
        self._transaction = transaction
        sandbox = PostgresSupportSandbox(
            session,
            self._scenario,
            isolation_confirmed=True,
            target=self._target,
            mutation_listener=self._on_mutation,
        )
        try:
            await sandbox.verify_target()
        except Exception as error:
            self._session = None
            self._transaction = None
            try:
                await transaction.rollback()
            except Exception as cleanup_error:
                error.add_note(f"sandbox verification rollback failed: {cleanup_error}")
            finally:
                try:
                    await session.close()
                except Exception as cleanup_error:
                    error.add_note(f"sandbox verification session close failed: {cleanup_error}")
            raise
        self._sandbox = sandbox
        self._emit(SimulationEventKind.ENVIRONMENT_CREATED, {"environment.id": self.environment_id})

    async def seed(self, state: object) -> None:
        """This method loads the approved disposable state into the sandbox."""
        if self._sandbox is None:
            raise EnvironmentRunError(detail="environment was not created before seeding")
        if not isinstance(state, SimulationState):
            raise EnvironmentRunError(detail="the seed must be a SimulationState")
        await self._sandbox.seed(state)
        self._emit(
            SimulationEventKind.ENVIRONMENT_SEEDED,
            {
                "environment.id": self.environment_id,
                "seed.customers": len(
                    {state.orders[i].customer_id for i in range(len(state.orders))}
                )
                + len({ticket.customer_id for ticket in state.tickets}),
                "seed.orders": len(state.orders),
                "seed.tickets": len(state.tickets),
                "seed.policies": len(state.policies),
            },
        )

    def connect(self) -> SupportRepository:
        """This method returns the repository that the real agent will use."""
        sandbox = self._require_created()
        repository = sandbox.repository
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
                repository,
                self._fault_script,
                event_sink=self._sink,
            )
        return repository

    async def destroy(self) -> None:
        """This method rolls back the disposable transaction."""
        if self._transaction is None:
            return
        transaction = self._transaction
        self._transaction = None
        session = self._session
        self._session = None
        self._sandbox = None
        try:
            await transaction.rollback()
        finally:
            if session is not None:
                await session.close()
        self._emit(
            SimulationEventKind.ENVIRONMENT_DESTROYED,
            {"environment.id": self.environment_id},
        )

    async def final_state(self) -> SimulationState:
        """This method captures the disposable state after the run."""
        self._require_created()
        session = self._session
        if session is None:
            raise EnvironmentRunError(detail="environment has no open session")
        orders = tuple(
            OrderRead.model_validate(row)
            for row in (await session.execute(select(Order).order_by(Order.id))).scalars()
        )
        tickets = tuple(
            TicketRead.model_validate(row)
            for row in (await session.execute(select(Ticket).order_by(Ticket.id))).scalars()
        )
        policies = tuple(
            PolicyDocumentRead.model_validate(row)
            for row in (
                await session.execute(select(PolicyDocument).order_by(PolicyDocument.id))
            ).scalars()
        )
        return SimulationState(orders=orders, tickets=tickets, policies=policies)

    def mutations(self) -> tuple[StateMutation, ...]:
        """This method returns the accepted mutations of the sandbox."""
        if self._sandbox is None:
            return ()
        return self._sandbox.mutations()

    def supported_tools(self) -> tuple[str, ...]:
        """This method returns the tools that this environment can serve."""
        if self._sandbox is None:
            return PostgresSupportSandbox.supported_tool_names
        return self._sandbox.supported_tools()

    def state_transitions(self) -> tuple[str, ...]:
        """This method returns the state transitions this environment can accept."""
        if self._sandbox is None:
            return ("order:delivered->refunded", "ticket:created")
        return self._sandbox.state_transitions()

    async def call(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> DependencyCallResult:
        """This method routes one dependency call through the real support path."""
        if self._sandbox is None:
            raise EnvironmentRunError(detail="environment was not created")
        return await self._sandbox.call(tool_name, arguments)

    async def sanitize(self, captured: Mapping[str, object]) -> None:
        """This method rejects captured payloads; state comes from the scenario."""
        if self._sandbox is None:
            raise EnvironmentRunError(detail="environment was not created")
        await self._sandbox.sanitize(captured)

    async def reset(self) -> None:
        """This method restores the exact approved state inside the transaction."""
        if self._sandbox is None:
            return
        await self._sandbox.reset()

    def _require_created(self) -> PostgresSupportSandbox:
        if self._sandbox is None:
            raise EnvironmentRunError(detail="environment was not created")
        return self._sandbox

    def _emit(
        self,
        kind: SimulationEventKind,
        attributes: Mapping[str, Scalar],
    ) -> None:
        if self._sink is not None:
            self._sink.emit(kind, attributes)

    def _on_mutation(self, mutation: StateMutation) -> None:
        """This method streams one accepted state mutation as an event."""
        self._emit(SimulationEventKind.STATE_MUTATION, mutation_event_attributes(mutation))
