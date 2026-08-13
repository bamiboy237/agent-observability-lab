"""This module defines the versioned live simulation event stream.

A run emits ordered ``SimulationEvent`` values for environment lifecycle,
model request and response metadata, tool selection and safe arguments,
dependency results, retries, injected faults, state mutations, evaluator
results, and completion. The same normalized sequence is persisted in the
run result. Every attribute must come from the event attribute allowlist:
secret model reasoning, credentials, unrestricted private text, and
forbidden payload bodies never enter the stream.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from enum import StrEnum
from time import perf_counter
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

SIMULATION_EVENT_SCHEMA_VERSION = "1.0.0"

Scalar = bool | int | float | str

SIMULATION_EVENT_ATTRIBUTE_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Environment lifecycle
        "environment.id",
        "seed.customers",
        "seed.orders",
        "seed.tickets",
        "seed.policies",
        # Model request and response metadata
        "model.provider",
        "model.name",
        "model.latency.ms",
        "model.tokens.input",
        "model.tokens.output",
        "model.tokens.total",
        "model.cost.usd",
        "model.run.id",
        # Tool selection and dependency results
        "tool",
        "tool.order.id",
        "tool.error.code",
        "db.operation",
        "db.latency.ms",
        "db.error.code",
        "retrieval.policy.version",
        # Retries and injected faults
        "retry.count",
        "fault.kind",
        "fault.tool",
        "fault.delay.ms",
        # State mutations
        "mutation.resource",
        "mutation.resource_id",
        "mutation.field",
        "mutation.before",
        "mutation.after",
        "mutation.reason.code",
        # Evaluator results
        "evaluator",
        "evaluator.version",
        "evaluator.passed",
        "evaluator.reason",
        # Turn facts
        "support.intent",
        "support.confidence",
        "support.outcome",
        "support.reason.code",
        "support.policy.grounded",
        # Completion totals
        "run.verdict",
        "run.total.latency.ms",
        "run.model.latency.ms",
        "run.tokens.input",
        "run.tokens.output",
        "run.tokens.total",
        "run.cost.usd",
        "run.retries",
        "run.errors",
    }
)


class SimulationEventKind(StrEnum):
    """This enum defines the normalized kind of one simulation event."""

    ENVIRONMENT_CREATED = "environment.created"
    ENVIRONMENT_SEEDED = "environment.seeded"
    ENVIRONMENT_DESTROYED = "environment.destroyed"
    MODEL_REQUEST = "model.request"
    MODEL_RESPONSE = "model.response"
    TOOL_SELECTED = "tool.selected"
    DEPENDENCY_RESULT = "dependency.result"
    RETRY = "retry"
    FAULT_INJECTED = "fault.injected"
    STATE_MUTATION = "state.mutation"
    EVALUATOR_RESULT = "evaluator.result"
    RUN_COMPLETED = "run.completed"


class SimulationEvent(BaseModel):
    """This class stores one ordered event of a simulation run.

    The sequence number starts at one and increases in emission order. The
    elapsed milliseconds come from the collector clock and are the same for
    the persisted transcript and every live subscriber.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=SIMULATION_EVENT_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    sequence: int = Field(ge=1)
    kind: SimulationEventKind
    elapsed_ms: float = Field(ge=0)
    attributes: dict[str, Scalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_attributes(self) -> "SimulationEvent":
        """This method rejects any attribute outside the event allowlist."""
        unknown = sorted(set(self.attributes) - SIMULATION_EVENT_ATTRIBUTE_ALLOWLIST)
        if unknown:
            raise ValueError(f"simulation event records non-allowlisted attributes {unknown!r}")
        return self


@runtime_checkable
class SimulationEventSink(Protocol):
    """This protocol defines the minimum emit operation of an event sink.

    Environment provisioners and fault wrappers emit through this sink so
    the runner can stream one ordered transcript.
    """

    def emit(
        self,
        kind: SimulationEventKind,
        attributes: Mapping[str, Scalar] | None = None,
    ) -> SimulationEvent: ...


class SimulationEventCollector:
    """This class collects one ordered simulation transcript.

    ``emit`` appends the event to the persisted sequence and hands the same
    event to every active subscriber of ``stream``. The collector owns the
    sequence numbers and the elapsed-time clock, so the live stream and the
    persisted transcript never diverge.
    """

    def __init__(self, *, subscriber_buffer: int = 256) -> None:
        if subscriber_buffer < 1:
            raise ValueError("subscriber_buffer must be at least 1")
        self._events: list[SimulationEvent] = []
        self._subscribers: list[asyncio.Queue[SimulationEvent]] = []
        self._subscriber_buffer = subscriber_buffer
        self._started = perf_counter()
        self._sequence = 0

    def emit(
        self,
        kind: SimulationEventKind,
        attributes: Mapping[str, Scalar] | None = None,
    ) -> SimulationEvent:
        """This method records one event and hands it to every subscriber."""
        self._sequence += 1
        event = SimulationEvent(
            sequence=self._sequence,
            kind=kind,
            elapsed_ms=round((perf_counter() - self._started) * 1000, 2),
            attributes=dict(attributes or {}),
        )
        self._events.append(event)
        for queue in self._subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
        return event

    def events(self) -> tuple[SimulationEvent, ...]:
        """This method returns the normalized persisted transcript."""
        return tuple(self._events)

    async def stream(
        self,
        *,
        until: Callable[[], bool] | None = None,
    ) -> AsyncIterator[SimulationEvent]:
        """This method streams events as the run emits them.

        The consumer stops the iteration when the run result is returned;
        the transcript in the run result stays complete regardless. A caller
        may pass ``until`` to terminate the stream cleanly when its predicate
        turns true and the queue is drained, for example when the background
        run task that emits into this collector completes.
        """
        queue: asyncio.Queue[SimulationEvent] = asyncio.Queue(
            maxsize=self._subscriber_buffer
        )
        self._subscribers.append(queue)
        try:
            while True:
                if until is not None and until() and queue.empty():
                    return
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    continue
        finally:
            self._subscribers.remove(queue)
