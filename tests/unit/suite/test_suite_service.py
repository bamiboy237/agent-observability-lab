"""This module tests the versioned regression suite service for checkpoint 7.2.

A suite names exact immutable case versions and is versioned with the same
deterministic rules as the case library: the same member set saves as
unchanged, a changed member set creates a visible new version, and unknown
or duplicate members are rejected.
"""

import pytest

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.bundle.compiler import compile_bundle
from app.domain.regression.schemas import CaseSourceType
from app.domain.regression.service import RegressionCaseService
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.scenarios import scenario_with_evidence
from app.domain.suite.errors import EmptySuiteError, InvalidSuiteError, SuiteNotFoundError
from app.domain.suite.repository import SuiteRepository
from app.domain.suite.schemas import CaseSuite, SuiteMemberRef, SuiteSaveStatus
from app.domain.suite.service import SuiteService, stable_suite_id
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


async def _bundle(scenario_id: str, **kwargs):
    source = FixtureTraceSource()
    evidence = await source.fetch_trace(scenario_id)
    scenario = scenario_with_evidence(scenario_id, evidence)
    return compile_bundle(
        scenario=scenario,
        evidence=evidence,
        coverage_items=COVERAGE_ITEMS,
        **{**REVIEW, **kwargs},
    )


async def _saved_case_repository(
    scenario_ids: tuple[str, ...],
) -> InMemoryRegressionCaseRepository:
    repository = InMemoryRegressionCaseRepository()
    service = RegressionCaseService(repository)
    for scenario_id in scenario_ids:
        await service.save_case(
            bundle=await _bundle(scenario_id),
            source_type=CaseSourceType.INCIDENT,
        )
    return repository


def _service(
    cases: InMemoryRegressionCaseRepository,
) -> SuiteService:
    suite_repository: SuiteRepository = InMemorySuiteRepository()
    return SuiteService(suite_repository, cases)


async def test_save_suite_creates_stable_immutable_version() -> None:
    cases = await _saved_case_repository(
        ("phase2-03-database-timeout", "phase2-05-unconfirmed-refund")
    )
    service = _service(cases)
    members = (
        SuiteMemberRef(case_id=saved.case_id, case_version=saved.case_version)
        for saved in (cases.rows[0], cases.rows[1])
    )
    refs = tuple(members)

    created = await service.save_suite(name="regression-core", members=refs)
    repeated = await service.save_suite(name="regression-core", members=refs)

    assert created.status is SuiteSaveStatus.CREATED
    assert created.suite_version == 1
    assert created.suite_id == stable_suite_id("regression-core")
    assert repeated.status is SuiteSaveStatus.UNCHANGED
    assert repeated.suite_id == created.suite_id
    assert repeated.suite_version == 1


async def test_save_suite_changed_members_creates_new_version_without_overwriting_history() -> None:
    cases = await _saved_case_repository(
        ("phase2-03-database-timeout", "phase2-05-unconfirmed-refund")
    )
    service = _service(cases)
    first = (
        SuiteMemberRef(case_id=cases.rows[0].case_id, case_version=cases.rows[0].case_version),
    )
    second = (
        SuiteMemberRef(case_id=cases.rows[0].case_id, case_version=cases.rows[0].case_version),
        SuiteMemberRef(case_id=cases.rows[1].case_id, case_version=cases.rows[1].case_version),
    )

    created = await service.save_suite(name="regression-core", members=first)
    updated = await service.save_suite(name="regression-core", members=second)

    assert updated.status is SuiteSaveStatus.UPDATED
    assert updated.suite_id == created.suite_id
    assert updated.suite_version == 2

    first_version = await service.get_suite(suite_id=created.suite_id, suite_version=1)
    second_version = await service.get_suite(suite_id=created.suite_id, suite_version=2)
    assert first_version.members == first
    assert second_version.members == second
    assert isinstance(first_version, CaseSuite)


async def test_save_suite_rejects_empty_unknown_and_duplicate_members() -> None:
    cases = await _saved_case_repository(("phase2-03-database-timeout",))
    service = _service(cases)
    existing = SuiteMemberRef(
        case_id=cases.rows[0].case_id, case_version=cases.rows[0].case_version
    )

    with pytest.raises(EmptySuiteError):
        await service.save_suite(name="empty-suite", members=())
    with pytest.raises(InvalidSuiteError):
        await service.save_suite(
            name="unknown-member",
            members=(SuiteMemberRef(case_id=existing.case_id, case_version=99),),
        )
    with pytest.raises(InvalidSuiteError):
        await service.save_suite(name="duplicate-member", members=(existing, existing))


async def test_list_suites_shows_latest_version_per_suite() -> None:
    cases = await _saved_case_repository(
        ("phase2-03-database-timeout", "phase2-05-unconfirmed-refund")
    )
    service = _service(cases)
    one = (SuiteMemberRef(case_id=cases.rows[0].case_id, case_version=cases.rows[0].case_version),)
    both = (
        SuiteMemberRef(case_id=cases.rows[0].case_id, case_version=cases.rows[0].case_version),
        SuiteMemberRef(case_id=cases.rows[1].case_id, case_version=cases.rows[1].case_version),
    )
    await service.save_suite(name="suite-a", members=one)
    await service.save_suite(name="suite-a", members=both)
    await service.save_suite(name="suite-b", members=both)

    summaries = await service.list_suites()

    by_name = {summary.name: summary for summary in summaries}
    assert len(by_name) == 2
    assert by_name["suite-a"].latest_version == 2
    assert by_name["suite-a"].member_count == 2
    assert by_name["suite-b"].latest_version == 1
    assert by_name["suite-b"].member_count == 2


async def test_get_missing_suite_version_raises_not_found() -> None:
    cases = await _saved_case_repository(("phase2-03-database-timeout",))
    service = _service(cases)
    ref = SuiteMemberRef(case_id=cases.rows[0].case_id, case_version=cases.rows[0].case_version)
    created = await service.save_suite(name="suite-a", members=(ref,))

    with pytest.raises(SuiteNotFoundError):
        await service.get_suite(suite_id=created.suite_id, suite_version=99)
    with pytest.raises(SuiteNotFoundError):
        await service.get_suite(
            suite_id=stable_suite_id("missing-suite"),
            suite_version=1,
        )
