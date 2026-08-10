"""This module tests how bundles carry versioned fault scripts safely.

Fault scripts ride inside the bundle so a run reproduces historical timeouts,
delays, and malformed responses deterministically. The compiler rejects fault
tools that no declared dependency covers and scans every fault argument for
forbidden content, and the bundle schema enforces the same rules on load.
"""

import pytest

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.bundle.compiler import compile_bundle
from app.domain.bundle.errors import ForbiddenDataError, InvalidBundleFixtureError
from app.domain.bundle.schemas import SimulationBundle
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.faults import FaultKind, FaultScript, FaultScriptEntry
from app.domain.simulation.scenarios import scenario_with_evidence

COVERAGE_ITEMS = (
    CoverageItem(
        dependency="support.database",
        kind="stateful",
        tools=("get_order_status",),
        state_transitions=(),
    ),
)

REVIEW = {
    "approved_request_message": "Use the approved synthetic request for this simulation.",
    "reviewer": "alice",
    "reviewed_at": "2026-08-08T00:00:00Z",
    "reason": "Reviewed and approved",
    "review_status": "approved",
}


async def _linked_scenario(scenario_id: str):
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(scenario_id)
    return scenario_with_evidence(scenario_id, evidence), evidence


def _timeout_script() -> FaultScript:
    return FaultScript(
        script_version="1",
        dependency="support.database",
        entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),),
    )


async def test_compile_bundle_carries_the_fault_script_deterministically() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    first = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        fault_script=_timeout_script(),
        **REVIEW,
    )
    second = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        fault_script=_timeout_script(),
        **REVIEW,
    )

    assert first.fault_script == _timeout_script()
    assert first.content_hash == second.content_hash
    assert first.bundle_id == second.bundle_id
    restored = SimulationBundle.model_validate(first.model_dump(mode="json"))
    assert restored.fault_script == _timeout_script()
    assert restored.content_hash == first.content_hash


async def test_compile_bundle_rejects_undeclared_fault_tool() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    script = FaultScript(
        script_version="1",
        dependency="support.database",
        entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="send_email"),),
    )
    with pytest.raises(InvalidBundleFixtureError, match="not covered"):
        compile_bundle(
            scenario=scenario,
            evidence=evidence,
            coverage_items=COVERAGE_ITEMS,
            fault_script=script,
            **REVIEW,
        )


async def test_compile_bundle_rejects_fault_script_for_undeclared_dependency() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    script = FaultScript(
        script_version="1",
        dependency="payments.external",
        entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),),
    )
    with pytest.raises(InvalidBundleFixtureError, match="no declared dependency"):
        compile_bundle(
            scenario=scenario,
            evidence=evidence,
            coverage_items=COVERAGE_ITEMS,
            fault_script=script,
            **REVIEW,
        )


async def test_compile_bundle_scans_fault_arguments_for_forbidden_content() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    script = FaultScript(
        script_version="1",
        dependency="support.database",
        entries=(
            FaultScriptEntry(
                kind=FaultKind.TIMEOUT,
                tool="get_order_status",
                arguments={"order_id": scenario.request.message},
            ),
        ),
    )
    with pytest.raises(ForbiddenDataError, match="forbidden content"):
        compile_bundle(
            scenario=scenario,
            evidence=evidence,
            coverage_items=COVERAGE_ITEMS,
            fault_script=script,
            **REVIEW,
        )


async def test_compile_bundle_rejects_secret_like_fault_arguments() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    script = FaultScript(
        script_version="1",
        dependency="support.database",
        entries=(
            FaultScriptEntry(
                kind=FaultKind.TIMEOUT,
                tool="get_order_status",
                arguments={"order_id": "sk-secret-key"},
            ),
        ),
    )
    with pytest.raises(ForbiddenDataError, match="forbidden value"):
        compile_bundle(
            scenario=scenario,
            evidence=evidence,
            coverage_items=COVERAGE_ITEMS,
            fault_script=script,
            **REVIEW,
        )


async def test_bundle_schema_rejects_undeclared_fault_tool_on_load() -> None:
    scenario, evidence = await _linked_scenario("phase2-03-database-timeout")
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        fault_script=_timeout_script(),
        **REVIEW,
    )
    dump = bundle.model_dump(mode="json")
    dump["fault_script"]["entries"][0]["tool"] = "send_email"

    with pytest.raises(InvalidBundleFixtureError, match="not covered"):
        SimulationBundle.model_validate(dump)
