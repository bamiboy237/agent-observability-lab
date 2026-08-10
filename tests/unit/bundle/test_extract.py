"""This module tests state and fixture extraction for checkpoint 5.3.

The extractor keeps owned-system seeds separate from simulated external
responses, preserves relationships between synthetic identifiers, includes
exact request-matching rules for recorded external responses, and never
copies the complete telemetry store or unrelated database rows.
"""

import pytest

from app.domain.bundle.errors import InvalidBundleFixtureError
from app.domain.bundle.extract import (
    extract_dependency_fixtures,
    extract_resource_seeds,
    redaction_decisions_for_seeds,
    synthetic_id,
)
from app.domain.bundle.schemas import DependencyFixture
from app.domain.simulation.scenarios import DELIVERED_ORDER, SCENARIO_BY_ID
from app.domain.simulation.schemas import DependencyCoverageRequirement


def test_extract_resource_seeds_preserves_relationships() -> None:
    scenario = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]
    seeds = extract_resource_seeds(scenario.initial_state)

    resources = {seed.resource: seed for seed in seeds}
    assert "order" in resources
    assert "policy" not in resources

    order = resources["order"].records[0]
    assert order["id"] == str(synthetic_id(DELIVERED_ORDER))
    assert order["customer_id"] == str(synthetic_id(scenario.request.customer_id))


def test_extract_resource_seeds_groups_by_type() -> None:
    scenario = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]
    seeds = extract_resource_seeds(scenario.initial_state)

    assert tuple(seed.resource for seed in seeds) == ("customer", "order")


def test_extract_resource_seeds_never_repeat_real_identifiers() -> None:
    scenario = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]
    seeds = extract_resource_seeds(scenario.initial_state)

    for seed in seeds:
        for record in seed.records:
            for key, value in record.items():
                if key.endswith("id") and isinstance(value, str):
                    assert value != str(DELIVERED_ORDER)
                    assert value != str(scenario.request.customer_id)


def test_redaction_decisions_cover_every_seed_resource() -> None:
    scenario = SCENARIO_BY_ID["phase2-05-unconfirmed-refund"]
    seeds = extract_resource_seeds(scenario.initial_state)

    decisions = redaction_decisions_for_seeds(seeds)
    fields = {decision.field for decision in decisions}
    assert {
        "customer.id",
        "customer.name",
        "customer.email",
        "order.id",
        "order.customer_id",
    } <= fields
    assert all(decision.reason for decision in decisions)


def test_extract_dependency_fixtures_rejects_stateful_dependency() -> None:
    scenario = SCENARIO_BY_ID["phase2-03-database-timeout"]
    fixture = DependencyFixture(
        dependency="support.database",
        adapter_name="support.database",
        adapter_version="4.0.0",
        tool="get_order_status",
        arguments={"order_id": str(scenario.initial_state.orders[0].id)},
        payload={"id": str(scenario.initial_state.orders[0].id), "status": "shipped"},
    )

    with pytest.raises(InvalidBundleFixtureError, match="not recorded"):
        extract_dependency_fixtures(scenario, dependency_fixtures=(fixture,))


def test_extract_dependency_fixtures_accepts_recorded_dependency() -> None:
    scenario = SCENARIO_BY_ID["phase2-03-database-timeout"]
    recorded = scenario.model_copy(
        update={
            "required_dependency_coverage": (
                DependencyCoverageRequirement(
                    dependency="order.lookup",
                    kind="recorded",
                    tools=("get_order_status",),
                ),
            )
        }
    )
    fixture = DependencyFixture(
        dependency="order.lookup",
        adapter_name="order.lookup",
        adapter_version="1.0.0",
        tool="get_order_status",
        arguments={"order_id": "synthetic-order"},
        payload={"status": "shipped"},
    )

    assert extract_dependency_fixtures(recorded, dependency_fixtures=(fixture,)) == (fixture,)


def test_extract_dependency_fixtures_rejects_undeclared_dependency() -> None:
    scenario = SCENARIO_BY_ID["phase2-03-database-timeout"]
    fixture = DependencyFixture(
        dependency="email.provider",
        adapter_name="email.provider",
        adapter_version="1.0.0",
        tool="send_email",
        arguments={},
        payload=None,
    )

    with pytest.raises(InvalidBundleFixtureError, match="not declared"):
        extract_dependency_fixtures(scenario, dependency_fixtures=(fixture,))


def test_extract_dependency_fixtures_rejects_undeclared_tool() -> None:
    scenario = SCENARIO_BY_ID["phase2-03-database-timeout"]
    scenario = scenario.model_copy(
        update={
            "required_dependency_coverage": (
                DependencyCoverageRequirement(
                    dependency="support.database",
                    kind="recorded",
                    tools=("get_order_status",),
                ),
            )
        }
    )
    fixture = DependencyFixture(
        dependency="support.database",
        adapter_name="support.database",
        adapter_version="4.0.0",
        tool="get_policy",
        arguments={},
        payload=None,
    )

    with pytest.raises(InvalidBundleFixtureError, match="not in the declared tools"):
        extract_dependency_fixtures(scenario, dependency_fixtures=(fixture,))


def test_extract_dependency_fixtures_requires_fixture_for_recorded_dependency() -> None:
    scenario = SCENARIO_BY_ID["phase2-03-database-timeout"]
    recorded = scenario.model_copy(
        update={
            "required_dependency_coverage": (
                DependencyCoverageRequirement(
                    dependency="support.database",
                    kind="recorded",
                    tools=("get_order_status",),
                ),
            )
        }
    )

    with pytest.raises(InvalidBundleFixtureError, match="no recorded fixture"):
        extract_dependency_fixtures(recorded, dependency_fixtures=())


def test_extract_dependency_fixtures_rejects_non_scalar_arguments() -> None:
    scenario = SCENARIO_BY_ID["phase2-03-database-timeout"]
    scenario = scenario.model_copy(
        update={
            "required_dependency_coverage": (
                DependencyCoverageRequirement(
                    dependency="support.database",
                    kind="recorded",
                    tools=("get_order_status",),
                ),
            )
        }
    )
    fixture = DependencyFixture(
        dependency="support.database",
        adapter_name="support.database",
        adapter_version="4.0.0",
        tool="get_order_status",
        arguments={"filters": {"status": "shipped"}},
        payload=None,
    )

    with pytest.raises(InvalidBundleFixtureError, match="not scalar"):
        extract_dependency_fixtures(scenario, dependency_fixtures=(fixture,))


def test_synthetic_id_is_stable() -> None:
    assert synthetic_id(DELIVERED_ORDER) == synthetic_id(DELIVERED_ORDER)
    assert synthetic_id(DELIVERED_ORDER) != DELIVERED_ORDER
