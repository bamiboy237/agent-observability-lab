"""This module tests the regression suite library against PostgreSQL for checkpoint 7.2.

A suite names exact immutable case versions. Saving the same member set is a
no-op. Changed members create a visible new version without overwriting
history. Unknown case versions are rejected. Tests run only against the
configured isolated database.
"""


import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.config import Settings
from app.db import get_session_factory
from app.domain.bundle.compiler import compile_bundle
from app.domain.regression.models import RegressionCaseRecord
from app.domain.regression.repository import SqlAlchemyRegressionCaseRepository
from app.domain.regression.schemas import CaseSourceType
from app.domain.regression.service import RegressionCaseService
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.scenarios import scenario_with_evidence
from app.domain.suite.errors import InvalidSuiteError
from app.domain.suite.models import RegressionSuiteRecord
from app.domain.suite.repository import SqlAlchemySuiteRepository
from app.domain.suite.schemas import SuiteMemberRef, SuiteSaveStatus
from app.domain.suite.service import SuiteService

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


@pytest.fixture(scope="module", autouse=True)
def apply_suite_migrations() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for suite integration tests")
    command.upgrade(Config("alembic.ini"), "head")


async def _saved_case_ids() -> list[object]:
    async with get_session_factory()() as session:
        rows = (await session.execute(select(RegressionCaseRecord.case_id))).scalars().all()
        return list(rows)


@pytest.mark.integration
async def test_postgres_saves_lists_and_versions_suites() -> None:
    try:
        async with get_session_factory().begin() as session:
            case_service = RegressionCaseService(SqlAlchemyRegressionCaseRepository(session))
            first = await case_service.save_case(
                bundle=await _bundle("phase2-03-database-timeout"),
                source_type=CaseSourceType.INCIDENT,
            )
            second = await case_service.save_case(
                bundle=await _bundle("phase2-05-unconfirmed-refund"),
                source_type=CaseSourceType.INCIDENT,
            )
            suite_service = SuiteService(
                SqlAlchemySuiteRepository(session),
                SqlAlchemyRegressionCaseRepository(session),
            )
            one = (
                SuiteMemberRef(case_id=first.case_id, case_version=first.case_version),
            )
            both = (
                SuiteMemberRef(case_id=first.case_id, case_version=first.case_version),
                SuiteMemberRef(case_id=second.case_id, case_version=second.case_version),
            )
            created = await suite_service.save_suite(name="db-suite", members=one)
            repeated = await suite_service.save_suite(name="db-suite", members=one)
            updated = await suite_service.save_suite(name="db-suite", members=both)

        assert created.status is SuiteSaveStatus.CREATED
        assert created.suite_version == 1
        assert repeated.status is SuiteSaveStatus.UNCHANGED
        assert repeated.suite_version == 1
        assert updated.status is SuiteSaveStatus.UPDATED
        assert updated.suite_id == created.suite_id
        assert updated.suite_version == 2

        async with get_session_factory().begin() as session:
            suite_service = SuiteService(
                SqlAlchemySuiteRepository(session),
                SqlAlchemyRegressionCaseRepository(session),
            )
            first_version = await suite_service.get_suite(
                suite_id=created.suite_id, suite_version=1
            )
            second_version = await suite_service.get_suite(
                suite_id=created.suite_id, suite_version=2
            )
            summaries = await suite_service.list_suites()

        assert first_version.members == one
        assert second_version.members == both
        assert len(summaries) == 1
        assert summaries[0].name == "db-suite"
        assert summaries[0].latest_version == 2
        assert summaries[0].member_count == 2

        async with get_session_factory().begin() as session:
            suite_service = SuiteService(
                SqlAlchemySuiteRepository(session),
                SqlAlchemyRegressionCaseRepository(session),
            )
            with pytest.raises(InvalidSuiteError):
                await suite_service.save_suite(
                    name="bad-suite",
                    members=(
                        SuiteMemberRef(case_id=first.case_id, case_version=99),
                    ),
                )
    finally:
        async with get_session_factory().begin() as session:
            await session.execute(
                delete(RegressionSuiteRecord).where(
                    RegressionSuiteRecord.name.in_(["db-suite", "bad-suite"])
                )
            )
            await session.execute(
                delete(RegressionCaseRecord).where(
                    RegressionCaseRecord.case_id.in_(await _saved_case_ids())
                )
            )
