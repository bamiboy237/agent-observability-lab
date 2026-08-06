"""This module tests coverage reports and path selection for checkpoint 4.5.

The registry routes by tool name, reports supported dependencies and state
transitions, reproduces the original recorded path, lets candidates take an
alternate supported stateful path, and rejects unknown paths with
missing_simulation_coverage.
"""

import pytest

from app.domain.simulation.adapters import (
    CoverageReport,
    SimulationAdapterRegistry,
    normalize_arguments,
)
from app.domain.simulation.errors import MissingSimulationCoverageError
from app.domain.simulation.recorded import RecordedOrderLookup
from app.domain.simulation.scenarios import SCENARIO_BY_ID, SHIPPED_ORDER
from app.domain.simulation.stateful import StatefulSupportAdapter


async def _timeout_then_success() -> RecordedOrderLookup:
    adapter = RecordedOrderLookup()
    await adapter.sanitize(
        {
            "get_order_status": {
                normalize_arguments({"order_id": SHIPPED_ORDER}): [
                    {"error_code": "timeout"},
                    {"payload": {"id": str(SHIPPED_ORDER), "status": "shipped"}},
                ]
            }
        }
    )
    return adapter


def test_coverage_report_lists_supported_dependencies() -> None:
    registry = SimulationAdapterRegistry((RecordedOrderLookup(),))
    report = registry.coverage_report()

    assert isinstance(report, CoverageReport)
    assert len(report.covered) == 1
    item = report.covered[0]
    assert item.dependency == "order.lookup"
    assert item.kind == "recorded"
    assert item.tools == ("get_order_status",)
    assert report.complete


def test_coverage_report_lists_stateful_transitions() -> None:
    registry = SimulationAdapterRegistry((StatefulSupportAdapter(),))
    report = registry.coverage_report()

    item = report.covered[0]
    assert item.dependency == "support.database"
    assert item.kind == "stateful"
    assert item.state_transitions == (
        "order:delivered->refunded",
        "ticket:created",
    )
    assert report.complete


def test_coverage_report_flags_missing_requirements() -> None:
    registry = SimulationAdapterRegistry((RecordedOrderLookup(),))
    scenario = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]

    report = registry.coverage_report(scenario)

    assert report.missing == ("support.database",)
    assert report.complete is False


def test_recorded_lookup_does_not_replace_database_sandbox() -> None:
    registry = SimulationAdapterRegistry((RecordedOrderLookup(),))
    scenario = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]

    report = registry.coverage_report(scenario)

    assert "support.database" in report.missing


def test_scenario_03_coverage_is_complete_with_stateful_adapter() -> None:
    registry = SimulationAdapterRegistry((StatefulSupportAdapter(),))
    scenario = SCENARIO_BY_ID["phase2-03-database-timeout"]

    assert registry.coverage_report(scenario).complete


def test_scenario_01_requires_no_coverage() -> None:
    registry = SimulationAdapterRegistry()
    scenario = SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"]

    assert registry.coverage_report(scenario).complete


async def test_original_path_replays_recorded_timeout_then_success() -> None:
    registry = SimulationAdapterRegistry((await _timeout_then_success(),))

    first = await registry.call("get_order_status", {"order_id": SHIPPED_ORDER})
    second = await registry.call("get_order_status", {"order_id": SHIPPED_ORDER})

    assert first.ok is False
    assert first.error_code == "timeout"
    assert second.ok is True
    assert second.payload["status"] == "shipped"


async def test_alternate_supported_path_uses_stateful_adapter() -> None:
    stateful = StatefulSupportAdapter()
    await stateful.seed(SCENARIO_BY_ID["phase2-03-database-timeout"].initial_state)
    registry = SimulationAdapterRegistry((stateful,))

    result = await registry.call("get_order_status", {"order_id": SHIPPED_ORDER})

    assert result.ok is True
    assert result.payload["status"] == "shipped"
    assert result.error_code is None


async def test_unknown_path_is_rejected_with_missing_coverage() -> None:
    registry = SimulationAdapterRegistry((await _timeout_then_success(),))

    with pytest.raises(MissingSimulationCoverageError) as excinfo:
        await registry.call("update_shipping_address", {"order_id": SHIPPED_ORDER})
    assert excinfo.value.code == "missing_simulation_coverage"


def test_duplicate_tool_across_adapters_is_rejected() -> None:
    first = RecordedOrderLookup()
    second = RecordedOrderLookup()

    with pytest.raises(ValueError, match="more than one adapter"):
        SimulationAdapterRegistry((first, second))


def test_empty_registry_reports_no_coverage() -> None:
    registry = SimulationAdapterRegistry()
    report = registry.coverage_report()

    assert report.covered == ()
    assert report.complete


def test_recorded_and_stateful_adapters_satisfy_the_same_contract() -> None:
    from typing import get_type_hints

    from app.domain.simulation.adapters import DependencyAdapter

    protocol = DependencyAdapter
    recorded = RecordedOrderLookup()
    stateful = StatefulSupportAdapter()

    for adapter in (recorded, stateful):
        assert isinstance(adapter, protocol)
        assert isinstance(adapter.dependency_name, str)
        assert adapter.kind in ("recorded", "stateful")
        for method in ("sanitize", "seed", "call", "reset"):
            assert callable(getattr(adapter, method))
        assert callable(adapter.supported_tools)
        assert callable(adapter.state_transitions)
        assert callable(adapter.mutations)
        assert get_type_hints(protocol)  # the protocol remains importable and typed
