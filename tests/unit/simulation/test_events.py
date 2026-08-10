"""This module tests the versioned simulation event stream (checkpoint 6.2).

Events are ordered, carry only allowlisted attributes, stream while a run
executes, and persist as one normalized sequence. Secret reasoning,
credentials, unrestricted private text, and forbidden payloads never enter
the stream.
"""

import asyncio

import pytest
from pydantic import ValidationError

from app.domain.simulation.events import (
    SIMULATION_EVENT_ATTRIBUTE_ALLOWLIST,
    SimulationEvent,
    SimulationEventCollector,
    SimulationEventKind,
)


def test_events_are_ordered_with_monotonic_sequence() -> None:
    collector = SimulationEventCollector()
    first = collector.emit(SimulationEventKind.ENVIRONMENT_CREATED, {"environment.id": "e1"})
    second = collector.emit(SimulationEventKind.MODEL_REQUEST, {"model.name": "gpt-5.2"})
    third = collector.emit(SimulationEventKind.RUN_COMPLETED, {"run.verdict": "reproduced"})

    assert (first.sequence, second.sequence, third.sequence) == (1, 2, 3)
    assert collector.events() == (first, second, third)
    assert first.kind is SimulationEventKind.ENVIRONMENT_CREATED
    assert first.elapsed_ms >= 0


def test_persisted_transcript_matches_live_stream() -> None:
    collector = SimulationEventCollector()

    async def watch() -> list[SimulationEvent]:
        streamed: list[SimulationEvent] = []
        async for event in collector.stream():
            streamed.append(event)
            if len(streamed) == 3:
                break
        return streamed

    async def main() -> None:
        task = asyncio.create_task(watch())
        await asyncio.sleep(0)
        collector.emit(SimulationEventKind.ENVIRONMENT_CREATED, {"environment.id": "e1"})
        collector.emit(SimulationEventKind.TOOL_SELECTED, {"tool": "get_order_status"})
        collector.emit(SimulationEventKind.RUN_COMPLETED, {"run.verdict": "reproduced"})
        streamed = await task
        assert [event.sequence for event in streamed] == [1, 2, 3]
        assert tuple(streamed) == collector.events()

    asyncio.run(main())


def test_event_rejects_non_allowlisted_attribute() -> None:
    with pytest.raises(ValidationError, match="non-allowlisted attributes"):
        SimulationEvent(
            sequence=1,
            kind=SimulationEventKind.MODEL_RESPONSE,
            elapsed_ms=0,
            attributes={"model.reasoning": "secret chain of thought"},
        )


def test_event_rejects_non_scalar_attribute_value() -> None:
    with pytest.raises(ValidationError):
        SimulationEvent(
            sequence=1,
            kind=SimulationEventKind.TOOL_SELECTED,
            elapsed_ms=0,
            attributes={"tool": {"nested": "payload"}},
        )


def test_event_allowlist_covers_every_streamed_attribute() -> None:
    kinds = SimulationEventKind
    samples = {
        kinds.ENVIRONMENT_CREATED: {"environment.id": "e1"},
        kinds.ENVIRONMENT_SEEDED: {"seed.orders": 2},
        kinds.ENVIRONMENT_DESTROYED: {"environment.id": "e1"},
        kinds.MODEL_REQUEST: {"model.provider": "openai", "model.name": "gpt-5.2"},
        kinds.MODEL_RESPONSE: {
            "model.latency.ms": 12.5,
            "model.tokens.input": 10,
            "model.cost.usd": 0.001,
            "model.run.id": "r1",
        },
        kinds.TOOL_SELECTED: {"tool": "get_order_status", "tool.order.id": "o1"},
        kinds.DEPENDENCY_RESULT: {"tool": "get_order_status", "tool.error.code": "timeout"},
        kinds.RETRY: {"retry.count": 1},
        kinds.FAULT_INJECTED: {"fault.kind": "timeout", "fault.tool": "get_order_status"},
        kinds.STATE_MUTATION: {
            "mutation.resource": "order",
            "mutation.resource_id": "o1",
            "mutation.field": "status",
            "mutation.before": "delivered",
            "mutation.after": "refunded",
            "mutation.reason.code": "refund_executed",
        },
        kinds.EVALUATOR_RESULT: {
            "evaluator": "authorization",
            "evaluator.version": "1.0.0",
            "evaluator.passed": True,
            "evaluator.reason": "pass",
        },
        kinds.RUN_COMPLETED: {
            "run.verdict": "reproduced",
            "run.total.latency.ms": 150.0,
            "run.tokens.total": 30,
            "run.cost.usd": 0.001,
            "run.retries": 1,
        },
    }
    for kind, attributes in samples.items():
        event = SimulationEvent(
            sequence=1,
            kind=kind,
            elapsed_ms=0,
            attributes=attributes,
        )
        assert set(event.attributes) <= SIMULATION_EVENT_ATTRIBUTE_ALLOWLIST
