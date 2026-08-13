"""This module tests the HTTP routes for cases and suites for checkpoint 7.3.

A trusted local client can save, list, and retrieve exact case and suite
versions through thin routes. Unknown ids and invalid inputs return stable
safe errors, and list operations enforce explicit limits.
"""

import asyncio

from fastapi.testclient import TestClient

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.api.cases_router import MAX_LIST_LIMIT, get_case_service
from app.api.dependencies import get_suite_service
from app.config import Settings
from app.domain.bundle.compiler import compile_bundle
from app.domain.regression.schemas import CaseSourceType
from app.domain.regression.service import RegressionCaseService
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.scenarios import scenario_with_evidence
from app.domain.suite.schemas import SuiteMemberRef
from app.domain.suite.service import SuiteService
from app.main import create_app
from tests.fakes.regression_repository import InMemoryRegressionCaseRepository
from tests.fakes.suite_repository import InMemorySuiteRepository

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


async def _bundle(scenario_id: str):
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(scenario_id)
    scenario = scenario_with_evidence(scenario_id, evidence)
    return compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )


async def _fixtures():
    cases = InMemoryRegressionCaseRepository()
    case_service = RegressionCaseService(cases)
    bundle = await _bundle("phase2-03-database-timeout")
    saved = await case_service.save_case(
        bundle=bundle,
        source_type=CaseSourceType.INCIDENT,
    )
    suite_service = SuiteService(InMemorySuiteRepository(), cases)
    suite = await suite_service.save_suite(
        name="api-suite",
        members=(SuiteMemberRef(case_id=saved.case_id, case_version=saved.case_version),),
    )
    return cases, case_service, suite_service, saved, suite, bundle


def _client(cases, case_service, suite_service) -> TestClient:
    settings = Settings(
        database_url="postgresql://user:password@localhost:5432/app",
        _env_file=None,
    )
    app = create_app(settings)
    app.dependency_overrides[get_case_service] = lambda: case_service
    app.dependency_overrides[get_suite_service] = lambda: suite_service
    return TestClient(app)


def test_post_cases_saves_an_accepted_bundle() -> None:
    cases, case_service, suite_service, saved, suite, bundle = asyncio.run(_fixtures())
    client = _client(cases, case_service, suite_service)

    response = client.post(
        "/cases",
        json={
            "bundle": bundle.model_dump(mode="json"),
            "source_type": "incident",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "unchanged"
    assert body["case_version"] == 1
    assert body["case_id"] == str(saved.case_id)


def test_post_cases_rejects_an_unapproved_bundle() -> None:
    cases, case_service, suite_service, saved, suite, bundle = asyncio.run(_fixtures())
    client = _client(cases, case_service, suite_service)
    rejected = bundle.model_copy(
        update={
            "review": {
                "status": "rejected",
                "reviewer": "alice",
                "reviewed_at": "2026-08-08T00:00:00Z",
                "reason": "Rejected in review",
            }
        }
    )

    response = client.post(
        "/cases",
        json={"bundle": rejected.model_dump(mode="json"), "source_type": "incident"},
    )

    assert response.status_code == 422


def test_get_cases_lists_with_limits_and_retrieves_exact_version() -> None:
    cases, case_service, suite_service, saved, suite, bundle = asyncio.run(_fixtures())
    client = _client(cases, case_service, suite_service)

    listing = client.get("/cases")
    assert listing.status_code == 200
    summaries = listing.json()
    assert len(summaries) == 1
    assert summaries[0]["case_id"] == str(saved.case_id)
    assert summaries[0]["latest_version"] == 1

    version = client.get(f"/cases/{saved.case_id}/versions/1")
    assert version.status_code == 200
    case = version.json()
    assert case["case_id"] == str(saved.case_id)
    assert case["case_version"] == 1
    assert case["bundle_content_hash"] == bundle.content_hash
    assert case["evidence_ref"]["trace_id"] == "phase2-03-database-timeout"

    missing = client.get(f"/cases/{saved.case_id}/versions/99")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "case_not_found"

    over_limit = client.get(f"/cases?limit={MAX_LIST_LIMIT + 1}")
    assert over_limit.status_code == 422


def test_post_suites_saves_and_lists_and_retrieves() -> None:
    cases, case_service, suite_service, saved, suite, bundle = asyncio.run(_fixtures())
    client = _client(cases, case_service, suite_service)

    response = client.post(
        "/suites",
        json={
            "name": "api-suite",
            "members": [{"case_id": str(saved.case_id), "case_version": 1}],
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "unchanged"
    assert response.json()["suite_version"] == 1

    listing = client.get("/suites")
    assert listing.status_code == 200
    assert listing.json()[0]["name"] == "api-suite"

    version = client.get(f"/suites/{suite.suite_id}/versions/1")
    assert version.status_code == 200
    assert version.json()["members"][0]["case_version"] == 1

    unknown = client.post(
        "/suites",
        json={
            "name": "bad-suite",
            "members": [{"case_id": str(saved.case_id), "case_version": 99}],
        },
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "invalid_suite"
