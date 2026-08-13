"""This module tests the Phase 7 HTTP routes against isolated PostgreSQL.

A trusted local client saves a case, creates a suite, starts one run through
the real sandbox, consumes the live events, and starts one suite comparison.
The hosted-model boundary is a deterministic substitute; the database is the
real isolated PostgreSQL branch. Tests run only against the configured
isolated database.
"""

import asyncio
import json
import os

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.config import Settings
from app.db import get_session_factory
from app.domain.bundle.compiler import compile_bundle
from app.domain.regression.models import RegressionCaseRecord
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.events import SimulationEventKind
from app.domain.simulation.scenarios import scenario_with_evidence
from app.domain.suite.models import RegressionSuiteRecord
from app.main import create_app

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


@pytest.fixture(scope="module", autouse=True)
def apply_lab_api_migrations() -> None:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for lab API integration tests")
    if settings.environment != "test" or os.environ.get("RUN_DATABASE_TESTS") != "1":
        pytest.skip("set ENVIRONMENT=test and RUN_DATABASE_TESTS=1 for an isolated database")
    command.upgrade(Config("alembic.ini"), "head")


async def _bundle():
    source = FixtureTraceSource()
    evidence = await source.fetch_trace("phase2-08-model-cost-comparison-primary")
    scenario = scenario_with_evidence("phase2-08-model-cost-comparison", evidence)
    return compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )


async def _wait_for(client: AsyncClient, path: str, token: str) -> dict:
    for _ in range(100):
        response = await client.get(path)
        body = response.json()
        if body["status"] != "running":
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"execution {token} did not finish")


@pytest.mark.integration
async def test_lab_api_saves_suite_runs_and_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fakes.scripted_model import build_scripted_model, order_status_plan

    settings = Settings()  # type: ignore[call-arg]
    bundle = await _bundle()
    from app.domain.simulation.runner import state_from_bundle

    plan = order_status_plan(state_from_bundle(bundle).orders[0].id)

    def build(config: object) -> object:
        return build_scripted_model(plan)

    monkeypatch.setattr("app.adapters.pydantic_ai_agent.build_pydantic_ai_model", build)

    from app.adapters.pydantic_ai_agent import ModelConfig
    from app.api.dependencies import get_execution_service
    from app.domain.execution.service import ExecutionService
    from app.domain.simulation.provisioner import postgres_provisioner_factory

    execution = ExecutionService(
        provisioner_factory=postgres_provisioner_factory(
            get_session_factory(),
            database_url=str(settings.migration_database_url),
            environment=settings.environment,
            isolation_confirmed=True,
        ),
        model_config=ModelConfig(provider="openai", name="gpt-5.2"),
    )
    app = create_app(settings)
    app.dependency_overrides[get_execution_service] = lambda: execution
    case_id = None
    suite_id = None
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            saved = await client.post(
                "/cases",
                json={"bundle": bundle.model_dump(mode="json"), "source_type": "incident"},
            )
            assert saved.status_code == 201, saved.text
            case_id = saved.json()["case_id"]

            listing = await client.get("/cases")
            assert listing.status_code == 200
            assert any(item["case_id"] == case_id for item in listing.json())

            version = await client.get(f"/cases/{case_id}/versions/1")
            assert version.status_code == 200
            assert version.json()["bundle_content_hash"] == bundle.content_hash

            suite = await client.post(
                "/suites",
                json={
                    "name": "lab-api-suite",
                    "members": [{"case_id": case_id, "case_version": 1}],
                },
            )
            assert suite.status_code == 201, suite.text
            suite_id = suite.json()["suite_id"]

            started = await client.post(
                "/runs",
                json={"case_id": case_id, "case_version": 1},
            )
            assert started.status_code == 202, started.text
            run_id = started.json()["execution_id"]

            events = []
            async with client.stream("GET", f"/runs/{run_id}/events") as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))
                        if events[-1].get("done"):
                            break

            status = await _wait_for(client, f"/runs/{run_id}", run_id)
            assert status["status"] == "completed"
            assert status["result"]["verdict"] == "reproduced"

            kinds = [event["kind"] for event in events if "kind" in event]
            assert SimulationEventKind.ENVIRONMENT_CREATED.value in kinds
            assert SimulationEventKind.RUN_COMPLETED.value in kinds
            assert events[-1] == {"done": True}

            candidate = bundle.configuration_versions.model_copy(
                update={"model_provider": "openai", "model_name": "gpt-5.3"}
            )
            comparison = await client.post(
                "/comparisons",
                json={
                    "suite_id": suite_id,
                    "suite_version": 1,
                    "change_type": "model",
                    "candidate": candidate.model_dump(mode="json"),
                },
            )
            assert comparison.status_code == 202, comparison.text
            comparison_id = comparison.json()["execution_id"]
            comparison_status = await _wait_for(
                client, f"/comparisons/{comparison_id}", comparison_id
            )
            assert comparison_status["status"] == "completed"
            assert comparison_status["result"]["suite_id"] == suite_id
            assert comparison_status["result"]["cases"][0]["case_id"] == case_id
    finally:
        async with get_session_factory().begin() as session:
            if suite_id is not None:
                await session.execute(
                    delete(RegressionSuiteRecord).where(
                        RegressionSuiteRecord.suite_id == suite_id
                    )
                )
            if case_id is not None:
                await session.execute(
                    delete(RegressionCaseRecord).where(
                        RegressionCaseRecord.case_id == case_id
                    )
                )
