"""This module tests the HTTP routes for runs, comparisons, and live events.

A trusted local client can start one run and one suite comparison, poll
their results, and consume the allowlisted live event stream, which
terminates cleanly. Model substitutes run only at the hosted-model boundary.
"""

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic_ai.models.function import FunctionModel

from app.adapters.pydantic_ai_agent import ModelConfig
from app.adapters.sources.fixture_source import FixtureTraceSource
from app.api.cases_router import get_case_service
from app.api.dependencies import get_execution_service, get_suite_service
from app.config import Settings
from app.domain.bundle.compiler import compile_bundle
from app.domain.execution.service import ExecutionService
from app.domain.regression.schemas import CaseSourceType
from app.domain.regression.service import RegressionCaseService
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.events import SimulationEventKind
from app.domain.simulation.scenarios import scenario_with_evidence
from app.domain.suite.schemas import SuiteMemberRef
from app.domain.suite.service import SuiteService
from app.main import create_app
from tests.fakes.provisioner import stateful_provisioner_factory
from tests.fakes.regression_repository import InMemoryRegressionCaseRepository
from tests.fakes.suite_repository import InMemorySuiteRepository

MODEL_CONFIG = ModelConfig(provider="openai", name="gpt-5.2")

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


async def _fixtures():
    source = FixtureTraceSource()
    evidence = await source.fetch_trace("phase2-08-model-cost-comparison-primary")
    scenario = scenario_with_evidence("phase2-08-model-cost-comparison", evidence)
    bundle = compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )
    cases = InMemoryRegressionCaseRepository()
    case_service = RegressionCaseService(cases)
    saved = await case_service.save_case(
        bundle=bundle,
        source_type=CaseSourceType.INCIDENT,
    )
    suite_service = SuiteService(InMemorySuiteRepository(), cases)
    suite = await suite_service.save_suite(
        name="run-suite",
        members=(SuiteMemberRef(case_id=saved.case_id, case_version=saved.case_version),),
    )
    case = await case_service.get_case(case_id=saved.case_id, case_version=saved.case_version)
    return case_service, suite_service, saved, suite, case


def install_scripted_model(monkeypatch, plans: dict[str, object]) -> None:
    """This function installs one deterministic model substitute per model name."""

    def build(config: object) -> FunctionModel:
        return build_scripted_model(plans[getattr(config, "name")])

    monkeypatch.setattr("app.adapters.pydantic_ai_agent.build_pydantic_ai_model", build)


def build_scripted_model(plan) -> FunctionModel:
    from tests.fakes.scripted_model import build_scripted_model as _build

    return _build(plan)


def _make_app(case_service, suite_service, execution_service, settings=None):
    settings = settings or Settings(
        database_url="postgresql://user:password@localhost:5432/app",
        _env_file=None,
        environment="test",
        model_provider="openai",
        model_name="gpt-5.2",
        model_api_key="test-key",
    )
    app = create_app(settings)
    app.dependency_overrides[get_case_service] = lambda: case_service
    app.dependency_overrides[get_suite_service] = lambda: suite_service
    if execution_service is not None:
        app.dependency_overrides[get_execution_service] = lambda: execution_service
    return app


@contextmanager
def _client(
    case_service,
    suite_service,
    execution_service=None,
    settings=None,
) -> Iterator[TestClient]:
    """This helper yields a client whose event loop persists across requests."""
    app = _make_app(case_service, suite_service, execution_service, settings)
    with TestClient(app) as client:
        yield client


def test_start_run_poll_and_consume_live_events(monkeypatch) -> None:
    case_service, suite_service, saved, suite, case = asyncio.run(_fixtures())
    from app.domain.simulation.runner import state_from_bundle
    from tests.fakes.scripted_model import order_status_plan

    order_id = state_from_bundle(case.bundle).orders[0].id
    install_scripted_model(monkeypatch, {"gpt-5.2": order_status_plan(order_id)})
    execution = ExecutionService(
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
    )

    with _client(case_service, suite_service, execution) as client:
        started = client.post(
            "/runs",
            json={"case_id": str(saved.case_id), "case_version": 1},
        )
        assert started.status_code == 202
        execution_id = started.json()["execution_id"]
        assert started.json()["kind"] == "run"
        assert started.json()["status"] == "running"

        status = None
        for _ in range(100):
            status = client.get(f"/runs/{execution_id}")
            if status.json()["status"] != "running":
                break
        assert status is not None
        assert status.json()["status"] == "completed"
        result = status.json()["result"]
        assert result["verdict"] == "reproduced"
        assert result["bundle_content_hash"] == case.bundle_content_hash
        assert result["evidence_ref"]["trace_id"] == "phase2-08-model-cost-comparison-primary"

        events = []
        with client.stream("GET", f"/runs/{execution_id}/events") as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    events.append(payload)
                    if payload.get("done"):
                        break
    kinds = [event["kind"] for event in events if "kind" in event]
    assert SimulationEventKind.ENVIRONMENT_CREATED.value in kinds
    assert SimulationEventKind.RUN_COMPLETED.value in kinds
    assert events[-1] == {"done": True}


def test_run_unknown_execution_returns_not_found() -> None:
    case_service, suite_service, saved, suite, case = asyncio.run(_fixtures())
    execution = ExecutionService(
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
    )

    with _client(case_service, suite_service, execution) as client:
        response = client.get(f"/runs/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "execution_not_found"


def test_run_unknown_case_returns_not_found() -> None:
    case_service, suite_service, saved, suite, case = asyncio.run(_fixtures())
    execution = ExecutionService(
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
    )

    with _client(case_service, suite_service, execution) as client:
        response = client.post(
            "/runs",
            json={"case_id": str(uuid4()), "case_version": 1},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "case_not_found"


def test_start_comparison_poll_result(monkeypatch) -> None:
    case_service, suite_service, saved, suite, case = asyncio.run(_fixtures())
    from app.domain.simulation.runner import state_from_bundle
    from tests.fakes.scripted_model import order_status_plan

    order_id = state_from_bundle(case.bundle).orders[0].id
    plan = order_status_plan(order_id)
    install_scripted_model(monkeypatch, {"gpt-5.2": plan, "gpt-5.3": plan})
    execution = ExecutionService(
        provisioner_factory=stateful_provisioner_factory(),
        model_config=MODEL_CONFIG,
    )

    candidate = case.bundle.configuration_versions.model_copy(
        update={"model_provider": "openai", "model_name": "gpt-5.3"}
    )
    with _client(case_service, suite_service, execution) as client:
        started = client.post(
            "/comparisons",
            json={
                "suite_id": str(suite.suite_id),
                "suite_version": 1,
                "change_type": "model",
                "candidate": candidate.model_dump(mode="json"),
            },
        )
        assert started.status_code == 202
        comparison_id = started.json()["execution_id"]
        assert started.json()["kind"] == "comparison"

        status = None
        for _ in range(100):
            status = client.get(f"/comparisons/{comparison_id}")
            if status.json()["status"] != "running":
                break
    assert status is not None
    assert status.json()["status"] == "completed"
    result = status.json()["result"]
    assert result["suite_id"] == str(suite.suite_id)
    assert result["change_type"] == "model"
    assert result["verdict"] in {"recommend_candidate", "keep_baseline", "inconclusive"}
    assert len(result["cases"]) == 1
    assert result["cases"][0]["case_id"] == str(saved.case_id)


def test_runs_require_a_configured_model() -> None:
    case_service, suite_service, saved, suite, case = asyncio.run(_fixtures())
    settings = Settings(
        database_url="postgresql://user:password@localhost:5432/app",
        _env_file=None,
        environment="test",
    )

    with _client(case_service, suite_service, None, settings) as client:
        response = client.post(
            "/runs",
            json={"case_id": str(saved.case_id), "case_version": 1},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_configured"


def test_runs_require_an_isolated_environment() -> None:
    case_service, suite_service, saved, suite, case = asyncio.run(_fixtures())
    settings = Settings(
        database_url="postgresql://user:password@localhost:5432/app",
        _env_file=None,
        environment="local",
        model_provider="openai",
        model_name="gpt-5.2",
        model_api_key="test-key",
    )

    with _client(case_service, suite_service, None, settings) as client:
        response = client.post(
            "/runs",
            json={"case_id": str(saved.case_id), "case_version": 1},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "sandbox_unavailable"
