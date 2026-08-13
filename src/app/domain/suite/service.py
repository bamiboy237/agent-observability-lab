"""This module defines the application service for the regression suite library."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from app.domain.regression.repository import RegressionCaseRepository
from app.domain.suite.errors import (
    EmptySuiteError,
    InvalidSuiteError,
    SuiteNotFoundError,
)
from app.domain.suite.repository import StoredSuite, SuiteRepository
from app.domain.suite.schemas import (
    CaseSuite,
    SuiteMemberRef,
    SuiteSaveResult,
    SuiteSaveStatus,
    SuiteSummary,
    suite_members_hash,
)

SUITE_NAMESPACE = UUID("1b7e6f2a-9c4d-4e8b-b5f1-3a0d6c2e8f47")


def stable_suite_id(name: str) -> UUID:
    """This function returns the stable suite id for one suite name.

    The same name always maps to the same suite id, so a changed member set
    becomes a new immutable version of the same suite instead of a new suite.
    """
    return uuid5(SUITE_NAMESPACE, name)


class SuiteService:
    """This class connects callers to the immutable suite persistence boundary."""

    def __init__(
        self,
        repository: SuiteRepository,
        cases: RegressionCaseRepository,
    ) -> None:
        self._repository = repository
        self._cases = cases

    async def save_suite(
        self,
        *,
        name: str,
        members: Sequence[SuiteMemberRef],
    ) -> SuiteSaveResult:
        """This method saves one explicit member set as a deterministic suite version.

        Every member must name an exact case version that exists. Saving the
        same member set again returns the existing version unchanged; a
        changed member set creates the next immutable version.
        """
        refs = tuple(members)
        if not refs:
            raise EmptySuiteError()
        seen: set[tuple[UUID, int]] = set()
        for member in refs:
            key = (member.case_id, member.case_version)
            if key in seen:
                raise InvalidSuiteError(
                    detail=f"duplicate member {member.case_id!r} v{member.case_version}"
                )
            seen.add(key)
            if await self._cases.case_version(member.case_id, member.case_version) is None:
                raise InvalidSuiteError(
                    detail=(
                        f"member case {member.case_id!r} v{member.case_version} "
                        "does not exist in the case library"
                    )
                )

        suite_id = stable_suite_id(name)
        members_hash = suite_members_hash(refs)
        latest = await self._repository.latest_suite(suite_id)
        if latest is not None and latest.members_hash == members_hash:
            return SuiteSaveResult(
                status=SuiteSaveStatus.UNCHANGED,
                suite_id=suite_id,
                suite_version=latest.suite_version,
            )

        suite_version = latest.suite_version + 1 if latest is not None else 1
        stored_suite = StoredSuite(
            id=uuid4(),
            suite_id=suite_id,
            suite_version=suite_version,
            name=name,
            members_hash=members_hash,
            members_json=[
                {"case_id": str(member.case_id), "case_version": member.case_version}
                for member in refs
            ],
            created_at=datetime.now(UTC),
        )
        saved = await self._repository.insert_version(stored_suite)
        if saved is None:
            latest = await self._repository.latest_suite(suite_id)
            if latest is None:
                raise SuiteNotFoundError(suite_id=suite_id, suite_version=None)
            status = (
                SuiteSaveStatus.UNCHANGED
                if latest.members_hash == members_hash
                else SuiteSaveStatus.UPDATED
            )
            return SuiteSaveResult(
                status=status,
                suite_id=suite_id,
                suite_version=latest.suite_version,
            )
        status = SuiteSaveStatus.UPDATED if latest is not None else SuiteSaveStatus.CREATED
        return SuiteSaveResult(
            status=status,
            suite_id=suite_id,
            suite_version=suite_version,
        )

    async def list_suites(self) -> tuple[SuiteSummary, ...]:
        """This method returns one summary per suite with its latest version."""
        rows = await self._repository.list_latest_suites()
        return tuple(
            SuiteSummary(
                suite_id=row.suite_id,
                name=row.name,
                latest_version=row.suite_version,
                member_count=len(row.members_json),
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        )

    async def get_suite(self, *, suite_id: UUID, suite_version: int) -> CaseSuite:
        """This method returns one exact immutable version of one suite."""
        row = await self._repository.suite_version(suite_id, suite_version)
        if row is None:
            raise SuiteNotFoundError(suite_id=suite_id, suite_version=suite_version)
        return CaseSuite(
            suite_id=row.suite_id,
            suite_version=row.suite_version,
            name=row.name,
            members=tuple(
                SuiteMemberRef(
                    case_id=UUID(str(member["case_id"])),
                    case_version=int(str(member["case_version"])),
                )
                for member in row.members_json
            ),
            created_at=row.created_at.isoformat(),
        )
