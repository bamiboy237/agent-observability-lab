"""This module runs one live hosted-model simulation through the full runner.

The check uses the provider and model from ``MODEL_PROVIDER`` and
``MODEL_NAME`` and an isolated database transaction that the runner rolls
back. The run must reproduce the reviewed expectation, and the allowlisted
event timeline is streamed and printed while the run executes: environment
lifecycle, model requests and responses, tool calls, database results,
retrievals, retries, state mutations, evaluator results, and completion.
The stream carries only allowlisted attributes, never private reasoning,
secrets, or unrestricted payloads. If the environment lacks the required
credentials, the test skips.
"""

import asyncio

import pytest
from sqlalchemy import func, select

from app.adapters.pydantic_ai_agent import ModelConfig
from app.adapters.sources.fixture_source import FixtureTraceSource
from app.config import Settings
from app.db import get_session_factory
from app.domain.bundle.compiler import compile_bundle
from app.domain.bundle.extract import synthetic_id
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.events import SimulationEventCollector, SimulationEventKind
from app.domain.simulation.provisioner import postgres_provisioner_factory
from app.domain.simulation.runner import RunVerdict, run_bundle
from app.domain.simulation.scenarios import scenario_with_evidence
from app.domain.support.models import Order, Ticket
from tests.live.conftest import build_live_settings

COVERAGE_ITEMS = (
    CoverageItem(
        dependency="support.database",
        kind="stateful",
        tools=("get_order_status", "get_policy", "propose_refund", "confirm_refund", "escalate"),
        state_transitions=("order:delivered->refunded", "ticket:created"),
    ),
)


@pytest.fixture(scope="module")
def live_runner_settings() -> Settings:
    settings = build_live_settings()
    if settings is None:
        pytest.skip(
            "Live simulation checks need MODEL_PROVIDER and MODEL_NAME (plus "
            "MODEL_API_KEY for hosted endpoints); set them to run these checks."
        )
    return settings


@pytest.fixture(scope="module")
def live_runner_model(live_runner_settings: Settings) -> ModelConfig:
    provider = live_runner_settings.model_provider
    model_name = live_runner_settings.model_name
    assert provider is not None and model_name is not None
    return ModelConfig(
        provider=provider,
        name=model_name,
        base_url=live_runner_settings.model_base_url,
        api_key=live_runner_settings.model_api_key,
    )


async def _stored_snapshot() -> tuple[list[tuple[object, object]], int]:
    async with get_session_factory()() as session:
        orders = (await session.execute(select(Order.id, Order.status).order_by(Order.id))).all()
        ticket_count = await session.scalar(select(func.count()).select_from(Ticket))
    return list(orders), ticket_count or 0


def _print_event(event: object) -> None:
    """This function prints one allowlisted event without any private content.

    The event carries only allowlisted attributes by construction, so the
    timeline can be printed verbatim: model metadata, tool names, safe
    identifiers, error codes, timings, and totals. Reasoning, secrets, and
    unrestricted payloads never appear.
    """
    attributes = ", ".join(f"{key}={value}" for key, value in event.attributes.items())
    print(
        f"  [{event.sequence:>2}] {event.elapsed_ms:9.1f}ms {event.kind.value:<22} {attributes}",
        flush=True,
    )


async def _stream_timeline(collector: SimulationEventCollector) -> list:
    """This function prints and collects events as the run emits them."""
    streamed = []
    print("live simulation event timeline (allowlisted):", flush=True)
    async for event in collector.stream():
        _print_event(event)
        streamed.append(event)
        if event.kind is SimulationEventKind.ENVIRONMENT_DESTROYED:
            break
    return streamed


async def test_live_simulation_reproduces_the_order_case(
    live_runner_model: ModelConfig,
    live_runner_settings: Settings,
) -> None:
    before = await _stored_snapshot()
    scenario_id = "phase2-08-model-cost-comparison"
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(f"{scenario_id}-primary")
    scenario = scenario_with_evidence(scenario_id, evidence)
    synthetic_order = synthetic_id(scenario.initial_state.orders[0].id)
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        approved_request_message=(
            f"What is the status of order {synthetic_order}? I want to know where "
            "it is and when it will arrive."
        ),
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Reviewed and approved",
        review_status="approved",
    )

    collector = SimulationEventCollector()
    watcher = asyncio.create_task(_stream_timeline(collector))
    await asyncio.sleep(0)
    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=postgres_provisioner_factory(
            lambda: get_session_factory()(),
            database_url=str(live_runner_settings.database_url),
            environment=live_runner_settings.environment,
            isolation_confirmed=True,
        ),
        model_config=live_runner_model,
        collector=collector,
    )
    streamed = await watcher

    assert tuple(streamed) == run.events
    assert run.response is not None
    assert run.verdict is RunVerdict.REPRODUCED
    assert run.bundle_content_hash == bundle.content_hash
    assert run.evidence_ref == bundle.evidence_ref
    assert run.events[0].kind.value == "environment.created"
    assert run.events[-1].kind.value == "environment.destroyed"
    assert any(e.kind.value == "model.request" for e in run.events)
    assert any(e.kind.value == "model.response" for e in run.events)
    assert any(e.kind.value == "tool.selected" for e in run.events)
    assert any(e.kind.value == "dependency.result" for e in run.events)
    assert any(e.kind.value == "evaluator.result" for e in run.events)
    assert run.events[-2].kind.value == "run.completed"
    # The live environment must leave the configured database untouched.
    assert await _stored_snapshot() == before
