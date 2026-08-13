"""This module defines the persistence boundary for the regression suite library."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.suite.models import RegressionSuiteRecord


@dataclass(frozen=True)
class StoredSuite:
    """This class stores one immutable suite version with its member set."""

    id: UUID
    suite_id: UUID
    suite_version: int
    name: str
    members_hash: str
    members_json: list[dict[str, object]]
    created_at: datetime


class SuiteRepository(Protocol):
    """This protocol defines the operations the suite service needs."""

    async def latest_suite(self, suite_id: UUID) -> StoredSuite | None: ...

    async def suite_version(self, suite_id: UUID, suite_version: int) -> StoredSuite | None: ...

    async def list_latest_suites(self) -> tuple[StoredSuite, ...]: ...

    async def insert_version(self, stored_suite: StoredSuite) -> StoredSuite | None: ...


class SqlAlchemySuiteRepository:
    """This class persists suite versions through one SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _from_record(record: RegressionSuiteRecord) -> StoredSuite:
        return StoredSuite(
            id=record.id,
            suite_id=record.suite_id,
            suite_version=record.suite_version,
            name=record.name,
            members_hash=record.members_hash,
            members_json=record.members_json,
            created_at=record.created_at,
        )

    async def latest_suite(self, suite_id: UUID) -> StoredSuite | None:
        statement = (
            select(RegressionSuiteRecord)
            .where(RegressionSuiteRecord.suite_id == suite_id)
            .order_by(RegressionSuiteRecord.suite_version.desc())
            .limit(1)
        )
        record = await self._session.scalar(statement)
        return self._from_record(record) if record is not None else None

    async def suite_version(self, suite_id: UUID, suite_version: int) -> StoredSuite | None:
        statement = (
            select(RegressionSuiteRecord)
            .where(RegressionSuiteRecord.suite_id == suite_id)
            .where(RegressionSuiteRecord.suite_version == suite_version)
        )
        record = await self._session.scalar(statement)
        return self._from_record(record) if record is not None else None

    async def list_latest_suites(self) -> tuple[StoredSuite, ...]:
        latest_versions = (
            select(
                RegressionSuiteRecord.suite_id,
                func.max(RegressionSuiteRecord.suite_version).label("max_version"),
            )
            .group_by(RegressionSuiteRecord.suite_id)
            .subquery()
        )
        statement = (
            select(RegressionSuiteRecord)
            .join(
                latest_versions,
                and_(
                    RegressionSuiteRecord.suite_id == latest_versions.c.suite_id,
                    RegressionSuiteRecord.suite_version == latest_versions.c.max_version,
                ),
            )
            .order_by(RegressionSuiteRecord.suite_id)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(self._from_record(record) for record in records)

    async def insert_version(self, stored_suite: StoredSuite) -> StoredSuite | None:
        """This method inserts one immutable suite version.

        If a concurrent transaction already stored the same suite version or
        the same member set, this method rolls back and returns ``None``.
        """
        record = RegressionSuiteRecord(
            id=uuid4(),
            suite_id=stored_suite.suite_id,
            suite_version=stored_suite.suite_version,
            name=stored_suite.name,
            members_hash=stored_suite.members_hash,
            members_json=stored_suite.members_json,
            created_at=stored_suite.created_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            return None
        return stored_suite
