"""Prove the full runner path against real PostgreSQL (checkpoint 6.1/6.3).

The runner provisions an isolated transaction, seeds synthetic state, runs the
real agent workflow against the real support services, repository, and SQL,
captures the final state, and rolls the transaction back. The scripted model
mocks only the hosted-model boundary. After the run the database holds
exactly its previous rows.
"""


import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import func, select

from app.adapters.pydantic_ai_agent import ModelConfig
from app.adapters.sources.fixture_source import FixtureTraceSource
from app.config import Settings
from app.db import get_session_factory
from app.domain.bundle.compiler import compile_bundle
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.faults import FaultKind, FaultScript, FaultScriptEntry
from app.domain.simulation.provisioner import postgres_provisioner_factory
from app.domain.simulation.runner import RunVerdict, run_bundle, state_from_bundle
from app.domain.simulation.scenarios import scenario_with_evidence
from app.domain.support.models import Order, Ticket
from tests.fakes.scripted_model import install_scripted_model, order_status_plan

COVERAGE_ITEMS = (
    CoverageItem(
        dependency="support.database",
        kind="stateful",
        tools=("get_order_status", "get_policy", "propose_refund", "confirm_refund", "escalate"),
        state_transitions=("order:delivered->refunded", "ticket:created"),
    ),
)

REVIEW = {
    "approved_request_message": "Use the approved synthetic request for this simulation.",
    "reviewer": "alice",
    "reviewed_at": "2026-08-08T00:00:00Z",
    "reason": "Reviewed and approved",
    "review_status": "approved",
}

MODEL_CONFIG = ModelConfig(provider="openai", name="gpt-5.2")


def _postgres_factory():
    settings = Settings()  # type: ignore[call-arg]
    return postgres_provisioner_factory(
        lambda: get_session_factory()(),
        database_url=str(settings.database_url),
        environment=settings.environment,
        isolation_confirmed=True,
    )


@pytest.fixture(scope="module", autouse=True)
def apply_migrations() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for runner integration tests")
    command.upgrade(Config("alembic.ini"), "head")


async def _stored_snapshot() -> tuple[list[tuple[object, object]], int]:
    async with get_session_factory()() as session:
        orders = (await session.execute(select(Order.id, Order.status).order_by(Order.id))).all()
        ticket_count = await session.scalar(select(func.count()).select_from(Ticket))
    return list(orders), ticket_count or 0


async def _bundle(
    scenario_id: str,
    *,
    trace_id: str | None = None,
    fault_script: FaultScript | None = None,
):
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(trace_id or scenario_id)
    scenario = scenario_with_evidence(scenario_id, evidence)
    return compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        fault_script=fault_script,
        **REVIEW,
    )


@pytest.mark.integration
async def test_runner_runs_the_real_workflow_against_postgres_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = await _stored_snapshot()
    bundle = await _bundle(
        "phase2-08-model-cost-comparison",
        trace_id="phase2-08-model-cost-comparison-primary",
    )
    state = state_from_bundle(bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=_postgres_factory(),
        model_config=MODEL_CONFIG,
    )

    assert run.verdict is RunVerdict.REPRODUCED
    assert run.evidence_ref == bundle.evidence_ref
    assert run.final_state.orders[0].status.value == "shipped"
    assert run.events[0].kind.value == "environment.created"
    assert run.events[-1].kind.value == "environment.destroyed"

    assert await _stored_snapshot() == before


@pytest.mark.integration
async def test_runner_reproduces_the_timeout_case_against_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = await _stored_snapshot()
    bundle = await _bundle(
        "phase2-03-database-timeout",
        fault_script=FaultScript(
            script_version="1",
            dependency="support.database",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order_status"),),
        ),
    )
    state = state_from_bundle(bundle)
    install_scripted_model(monkeypatch, order_status_plan(state.orders[0].id))

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=_postgres_factory(),
        model_config=MODEL_CONFIG,
    )

    assert run.verdict is RunVerdict.REPRODUCED
    assert run.retries == 1
    assert any(e.kind.value == "retry" for e in run.events)
    assert any(e.kind.value == "fault.injected" for e in run.events)

    assert await _stored_snapshot() == before


@pytest.mark.integration
async def test_runner_records_a_real_refund_mutation_against_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.agent.schemas import ReasonCode

    before = await _stored_snapshot()
    scenario_id = "phase2-05-unconfirmed-refund"
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(scenario_id)
    scenario = scenario_with_evidence(scenario_id, evidence)
    scenario = scenario.model_copy(
        update={
            "request": scenario.request.model_copy(update={"refund_confirmed": True}),
            "content_hash": None,
        }
    )
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )
    state = state_from_bundle(bundle)
    from tests.fakes.scripted_model import refund_plan

    install_scripted_model(
        monkeypatch,
        refund_plan(state.orders[0].id, confirmed=True),
    )

    run = await run_bundle(
        bundle=bundle,
        provisioner_factory=_postgres_factory(),
        model_config=MODEL_CONFIG,
    )

    assert run.response is not None
    assert run.response.reason_code is ReasonCode.REFUND_CONFIRMED
    assert run.mutations and run.mutations[0].reason_code == "refund_executed"
    assert run.final_state.orders[0].status.value == "refunded"
    mutation_events = [e for e in run.events if e.kind.value == "state.mutation"]
    assert mutation_events
    assert mutation_events[0].attributes["mutation.reason.code"] == "refund_executed"
    assert mutation_events[0].attributes["mutation.after"] == "refunded"

    assert await _stored_snapshot() == before
