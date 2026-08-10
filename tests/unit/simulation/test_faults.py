"""This module tests the versioned fault-script contract (checkpoint 6.2).

Fault scripts inject timeouts, delays, transient errors, and malformed
responses at an owned-system boundary. Faulted calls fail exactly as the
script declares and successful calls still pass through the real repository
path. Entries match by tool and normalized arguments, apply once by default,
and repeat when declared.
"""

from uuid import uuid4

import pytest
from tests.fakes.support_repository import InMemorySupportRepository

from app.domain.simulation.errors import MalformedResponseError
from app.domain.simulation.events import SimulationEventCollector, SimulationEventKind
from app.domain.simulation.faults import (
    FaultInjectingRepository,
    FaultKind,
    FaultScript,
    FaultScriptEntry,
)


def make_repository() -> InMemorySupportRepository:
    return InMemorySupportRepository()


async def test_timeout_fault_raises_once_then_passes_through() -> None:
    repository = make_repository()
    wrapped = FaultInjectingRepository(
        repository,
        FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),),
        ),
    )
    order_id = uuid4()

    with pytest.raises(TimeoutError):
        await wrapped.get_order(order_id)
    assert await wrapped.get_order(order_id) is None


async def test_repeat_timeout_fault_raises_on_every_call() -> None:
    repository = make_repository()
    wrapped = FaultInjectingRepository(
        repository,
        FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(
                FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status", repeat=True),
            ),
        ),
    )

    with pytest.raises(TimeoutError):
        await wrapped.get_order(uuid4())
    with pytest.raises(TimeoutError):
        await wrapped.get_order(uuid4())


async def test_delay_fault_sleeps_then_uses_the_real_path() -> None:
    import time

    repository = make_repository()
    wrapped = FaultInjectingRepository(
        repository,
        FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(
                FaultScriptEntry(
                    kind=FaultKind.DELAY,
                    tool="get_order_status",
                    delay_ms=30,
                    repeat=True,
                ),
            ),
        ),
    )

    started = time.perf_counter()
    assert await wrapped.get_order(uuid4()) is None
    elapsed = (time.perf_counter() - started) * 1000
    assert elapsed >= 25
    assert await wrapped.get_order(uuid4()) is None


async def test_entry_arguments_match_normalized_call_arguments() -> None:
    repository = make_repository()
    target = uuid4()
    other = uuid4()
    wrapped = FaultInjectingRepository(
        repository,
        FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(
                FaultScriptEntry(
                    kind=FaultKind.TIMEOUT,
                    tool="get_order_status",
                    arguments={"order_id": str(target)},
                ),
            ),
        ),
    )

    assert await wrapped.get_order(other) is None
    with pytest.raises(TimeoutError):
        await wrapped.get_order(target)


async def test_transient_error_raises_connection_error() -> None:
    wrapped = FaultInjectingRepository(
        make_repository(),
        FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(FaultScriptEntry(kind=FaultKind.TRANSIENT_ERROR, tool="get_policy"),),
        ),
    )

    with pytest.raises(ConnectionError):
        await wrapped.get_policy("refund-and-delivery")


async def test_malformed_response_raises_typed_error() -> None:
    wrapped = FaultInjectingRepository(
        make_repository(),
        FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(FaultScriptEntry(kind=FaultKind.MALFORMED_RESPONSE, tool="get_policy"),),
        ),
    )

    with pytest.raises(MalformedResponseError):
        await wrapped.get_policy("refund-and-delivery")


async def test_fault_events_stream_into_the_collector() -> None:
    collector = SimulationEventCollector()
    wrapped = FaultInjectingRepository(
        make_repository(),
        FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(
                FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),
                FaultScriptEntry(
                    kind=FaultKind.DELAY,
                    tool="get_order_status",
                    delay_ms=5,
                ),
            ),
        ),
        event_sink=collector,
    )

    with pytest.raises(TimeoutError):
        await wrapped.get_order(uuid4())
    await wrapped.get_order(uuid4())

    fault_events = [e for e in collector.events() if e.kind is SimulationEventKind.FAULT_INJECTED]
    assert [e.attributes["fault.kind"] for e in fault_events] == ["timeout", "delay"]
    assert fault_events[0].attributes["fault.tool"] == "get_order_status"
    assert fault_events[1].attributes["fault.delay.ms"] == 5


def test_delay_entry_requires_delay_ms() -> None:
    with pytest.raises(ValueError, match="delay_ms"):
        FaultScriptEntry(kind=FaultKind.DELAY, tool="get_order_status")
