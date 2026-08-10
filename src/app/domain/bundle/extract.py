"""This module extracts state and fixtures for one simulation bundle.

The extractor keeps owned-system seeds separate from simulated external
responses, preserves relationships between synthetic identifiers, includes
exact request-matching rules for recorded external responses, and never
copies the complete telemetry store or unrelated database rows. Only the
state declared by the selected scenario is extracted.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID, uuid5

from app.domain.bundle.allowlist import validate_resource_seed
from app.domain.bundle.errors import InvalidBundleFixtureError
from app.domain.bundle.schemas import (
    DependencyFixture,
    EnvironmentResourceSeed,
    RedactionDecision,
)
from app.domain.simulation.adapters import normalize_arguments
from app.domain.simulation.schemas import SimulationScenario, SimulationState

SYNTHETIC_NAMESPACE = UUID("9d4e5f6a-7b8c-4d1e-9f2a-3b4c5d6e7f80")

_SYNTHETIC_REASON = "Replaced with a stable synthetic value to preserve relationships"


def synthetic_id(original: UUID) -> UUID:
    """This function returns a stable synthetic value for one identifier.

    The same original identifier always maps to the same synthetic value, so
    relationships between identifiers survive replay while real identifiers
    never appear in the captured bundle state.
    """
    return uuid5(SYNTHETIC_NAMESPACE, f"synth:{original}")


def _customer_records(state: SimulationState) -> tuple[dict[str, object], ...]:
    customer_ids = {state.orders[i].customer_id for i in range(len(state.orders))}
    for ticket in state.tickets:
        customer_ids.add(ticket.customer_id)
    return tuple(
        {
            "id": str(synthetic_id(customer_id)),
            "name": f"customer-{str(synthetic_id(customer_id))[:8]}",
            "email": f"customer-{str(synthetic_id(customer_id))[:8]}@example.invalid",
        }
        for customer_id in sorted(customer_ids, key=str)
    )


def _order_records(state: SimulationState) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "id": str(synthetic_id(order.id)),
            "customer_id": str(synthetic_id(order.customer_id)),
            "status": order.status.value,
            "total_amount": str(order.total_amount),
        }
        for order in state.orders
    )


def _ticket_records(state: SimulationState) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "id": str(synthetic_id(ticket.id)),
            "customer_id": str(synthetic_id(ticket.customer_id)),
            "order_id": (
                str(synthetic_id(ticket.order_id)) if ticket.order_id is not None else None
            ),
            "subject": ticket.subject,
            "status": ticket.status.value,
        }
        for ticket in state.tickets
    )


def _policy_records(state: SimulationState) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "id": str(synthetic_id(policy.id)),
            "slug": policy.slug,
            "version": policy.version,
            "title": policy.title,
            "content": policy.content,
            "content_hash": policy.content_hash,
        }
        for policy in state.policies
    )


def extract_resource_seeds(
    state: SimulationState,
    *,
    adapter_name: str = "support.database",
    adapter_version: str = "4.0.0",
) -> tuple[EnvironmentResourceSeed, ...]:
    """This function extracts owned-system seeds from one scenario state.

    Every order references its synthetic customer id and every ticket
    references its synthetic order id, so relationships remain intact.
    Customers are seeded only when the scenario's orders or tickets
    reference them. Seeds carry only allowlisted scalar fields.
    """
    seeds: list[EnvironmentResourceSeed] = []
    extractors: tuple[
        tuple[str, tuple[dict[str, object], ...]],
        ...,
    ] = (
        ("customer", _customer_records(state)),
        ("order", _order_records(state)),
        ("ticket", _ticket_records(state)),
        ("policy", _policy_records(state)),
    )
    for resource, records in extractors:
        if not records:
            continue
        seeds.append(
            EnvironmentResourceSeed(
                resource=resource,
                adapter_name=adapter_name,
                adapter_version=adapter_version,
                records=records,
            )
        )
        for record in records:
            validate_resource_seed(resource, record)
    return tuple(seeds)


def redaction_decisions_for_seeds(
    seeds: Sequence[EnvironmentResourceSeed],
) -> tuple[RedactionDecision, ...]:
    """This function records the default redaction decisions for one seed set.

    Every seed record replaces real identifiers with stable synthetic
    values; the decisions document that replacement for review.
    """
    fields_by_resource: Mapping[str, tuple[str, ...]] = {
        "customer": ("customer.id", "customer.name", "customer.email"),
        "order": ("order.id", "order.customer_id"),
        "ticket": ("ticket.id", "ticket.customer_id", "ticket.order_id"),
        "policy": ("policy.id",),
    }
    decisions: list[RedactionDecision] = []
    for seed in seeds:
        for field in fields_by_resource.get(seed.resource, ()):
            decisions.append(RedactionDecision(field=field, reason=_SYNTHETIC_REASON))
    return tuple(decisions)


def extract_dependency_fixtures(
    scenario: SimulationScenario,
    *,
    dependency_fixtures: Sequence[DependencyFixture],
) -> tuple[DependencyFixture, ...]:
    """This function validates the recorded fixtures for one scenario.

    Every fixture must belong to a dependency that the scenario declares,
    and every fixture tool must be in that dependency's declared tools.
    A recorded dependency without any fixture cannot serve a single
    request, so it is rejected. Argument values must be scalar so the exact
    request-matching rule stays deterministic.
    """
    declared = {
        requirement.dependency: requirement
        for requirement in scenario.required_dependency_coverage
    }
    recorded: set[str] = {
        requirement.dependency
        for requirement in scenario.required_dependency_coverage
        if requirement.kind == "recorded"
    }
    for dependency in recorded:
        if not any(fixture.dependency == dependency for fixture in dependency_fixtures):
            raise InvalidBundleFixtureError(
                detail=(
                    f"recorded dependency {dependency!r} of scenario "
                    f"{scenario.scenario_id!r} has no recorded fixture; "
                    "a recorded dependency must carry at least one response"
                )
            )
    for fixture in dependency_fixtures:
        requirement = declared.get(fixture.dependency)
        if requirement is None:
            raise InvalidBundleFixtureError(
                detail=(
                    f"dependency {fixture.dependency!r} is not declared by scenario "
                    f"{scenario.scenario_id!r}"
                )
            )
        if requirement.kind != "recorded":
            raise InvalidBundleFixtureError(
                detail=(
                    f"dependency {fixture.dependency!r} is {requirement.kind!r}, not recorded; "
                    "owned-system state must use an ephemeral resource seed"
                )
            )
        tools = requirement.tools
        if tools and fixture.tool not in tools:
            raise InvalidBundleFixtureError(
                detail=(
                    f"fixture tool {fixture.tool!r} is not in the declared tools "
                    f"{tools!r} for dependency {fixture.dependency!r}"
                )
            )
        try:
            normalize_arguments(fixture.arguments)
        except Exception as error:
            raise InvalidBundleFixtureError(
                detail=f"fixture arguments for {fixture.dependency!r} are not scalar"
            ) from error
    return tuple(dependency_fixtures)
