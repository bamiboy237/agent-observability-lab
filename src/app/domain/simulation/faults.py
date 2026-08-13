"""This module defines the versioned fault-script contract and boundary wrapper.

A fault script reproduces historical timeouts, delays, transient errors, and
malformed responses at one explicit dependency boundary. The wrapper sits
around the owned-system boundary: faulted calls raise or sleep exactly as the
script declares, and every successful call still passes through the real
application service and repository path. A fault entry matches by tool name
and, when declared, by normalized arguments. Entries apply once by default;
``repeat`` entries apply on every matching call, which reproduces a component
that is slow or failing for the whole case.
"""

import asyncio
from collections.abc import Mapping
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.simulation.adapters import normalize_arguments
from app.domain.simulation.errors import MalformedResponseError
from app.domain.simulation.events import SimulationEventKind, SimulationEventSink
from app.domain.support.repository import SupportRepository
from app.domain.support.schemas import OrderRead, PolicyDocumentRead, TicketCreate, TicketRead

FAULT_SCRIPT_SCHEMA_VERSION = "1.0.0"

Scalar = bool | int | float | str


class FaultKind(StrEnum):
    """This enum defines the fault kinds a script may inject."""

    TIMEOUT = "timeout"
    TRANSIENT_ERROR = "transient_error"
    DELAY = "delay"
    MALFORMED_RESPONSE = "malformed_response"


class FaultScriptEntry(BaseModel):
    """This class declares one fault injection for one tool boundary."""

    model_config = ConfigDict(extra="forbid")

    kind: FaultKind
    tool: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=200)
    arguments: dict[str, object] = Field(default_factory=dict)
    delay_ms: int | None = Field(default=None, ge=1)
    repeat: bool = False

    @model_validator(mode="after")
    def validate_delay(self) -> "FaultScriptEntry":
        """This method requires a delay value exactly for the delay kind."""
        if self.kind is FaultKind.DELAY and self.delay_ms is None:
            raise ValueError("a delay fault requires delay_ms")
        if self.kind is not FaultKind.DELAY and self.delay_ms is not None:
            raise ValueError("only a delay fault may carry delay_ms")
        return self


class FaultScript(BaseModel):
    """This class stores one versioned fault script.

    The script names the dependency boundary it wraps and a stable script
    version. An empty arguments mapping matches any call for the tool; a
    non-empty mapping must normalize to the exact call arguments.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=FAULT_SCRIPT_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    script_version: str = Field(min_length=1, max_length=50)
    dependency: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=100)
    entries: tuple[FaultScriptEntry, ...] = ()


class FaultInjectingRepository:
    """This class wraps one owned-system repository with a fault script.

    The wrapper maps repository operations to the tool names that the agent
    uses. A matching fault raises, sleeps, or is consumed before the real
    call; otherwise the call passes straight through to the wrapped
    repository, which is the real application and database path.
    """

    def __init__(
        self,
        repository: SupportRepository,
        script: FaultScript,
        event_sink: SimulationEventSink | None = None,
    ) -> None:
        self._repository = repository
        self._script = script
        self._sink = event_sink
        self._consumed: set[int] = set()

    async def get_order(self, order_id: UUID) -> OrderRead | None:
        await self._maybe_fault("get_order_status", {"order_id": str(order_id)})
        return await self._repository.get_order(order_id)

    async def save_order(self, order: OrderRead) -> OrderRead | None:
        await self._maybe_fault("confirm_refund", {"order_id": str(order.id)})
        return await self._repository.save_order(order)

    async def refund_order_if_delivered(
        self, order_id: UUID, customer_id: UUID
    ) -> OrderRead | None:
        await self._maybe_fault("confirm_refund", {"order_id": str(order_id)})
        return await self._repository.refund_order_if_delivered(order_id, customer_id)

    async def create_ticket(self, ticket: TicketCreate) -> TicketRead:
        await self._maybe_fault("escalate", {"subject": ticket.subject})
        return await self._repository.create_ticket(ticket)

    async def get_ticket(self, ticket_id: UUID) -> TicketRead | None:
        return await self._repository.get_ticket(ticket_id)

    async def get_policy(
        self,
        slug: str,
        version: str | None = None,
    ) -> PolicyDocumentRead | None:
        arguments: dict[str, object] = {"slug": slug}
        if version is not None:
            arguments["version"] = version
        await self._maybe_fault("get_policy", arguments)
        return await self._repository.get_policy(slug, version)

    async def _maybe_fault(
        self,
        tool: str,
        arguments: Mapping[str, object],
    ) -> None:
        entry = self._next_entry(tool, arguments)
        if entry is None:
            return
        attributes: dict[str, Scalar] = {
            "fault.kind": entry.kind.value,
            "fault.tool": tool,
        }
        if entry.kind is FaultKind.DELAY:
            if self._sink is not None:
                attributes["fault.delay.ms"] = entry.delay_ms or 0
                self._sink.emit(SimulationEventKind.FAULT_INJECTED, attributes)
            await asyncio.sleep(float(entry.delay_ms or 0) / 1000.0)
            return
        if self._sink is not None:
            self._sink.emit(SimulationEventKind.FAULT_INJECTED, attributes)
        if entry.kind is FaultKind.TIMEOUT:
            raise TimeoutError(f"injected timeout for tool {tool!r}")
        if entry.kind is FaultKind.TRANSIENT_ERROR:
            raise ConnectionError(f"injected transient error for tool {tool!r}")
        raise MalformedResponseError(dependency=self._script.dependency, tool=tool)

    def _next_entry(
        self,
        tool: str,
        arguments: Mapping[str, object],
    ) -> FaultScriptEntry | None:
        try:
            normalized = normalize_arguments(arguments)
        except Exception:
            normalized = None
        for index, entry in enumerate(self._script.entries):
            if entry.tool != tool:
                continue
            if entry.arguments:
                try:
                    if normalize_arguments(entry.arguments) != normalized:
                        continue
                except Exception:
                    continue
            if entry.repeat or index not in self._consumed:
                if not entry.repeat:
                    self._consumed.add(index)
                return entry
        return None
