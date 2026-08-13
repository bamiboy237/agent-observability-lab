"""This module defines the persistence boundary for the regression case library."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.regression.models import RegressionCaseRecord


@dataclass(frozen=True)
class StoredCase:
    """This class stores one immutable case version with its serialized bundle."""

    id: UUID
    case_id: UUID
    case_version: int
    source_type: str
    scenario_id: str
    bundle_content_hash: str
    source_platform: str | None
    source_trace_id: str | None
    source_url: str | None
    evidence_content_hash: str | None
    configuration_version: str | None
    bundle_json: dict[str, object]
    created_at: datetime


class RegressionCaseRepository(Protocol):
    """This protocol defines the operations the case service needs."""

    async def latest_case(self, case_id: UUID) -> StoredCase | None: ...

    async def case_version(self, case_id: UUID, case_version: int) -> StoredCase | None: ...

    async def list_latest_cases(self) -> tuple[StoredCase, ...]: ...

    async def insert_version(self, stored_case: StoredCase) -> StoredCase | None: ...


class SqlAlchemyRegressionCaseRepository:
    """This class persists case versions through one SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _from_record(record: RegressionCaseRecord) -> StoredCase:
        return StoredCase(
            id=record.id,
            case_id=record.case_id,
            case_version=record.case_version,
            source_type=record.source_type,
            scenario_id=record.scenario_id,
            bundle_content_hash=record.bundle_content_hash,
            source_platform=record.source_platform,
            source_trace_id=record.source_trace_id,
            source_url=record.source_url,
            evidence_content_hash=record.evidence_content_hash,
            configuration_version=record.configuration_version,
            bundle_json=record.bundle_json,
            created_at=record.created_at,
        )

    async def latest_case(self, case_id: UUID) -> StoredCase | None:
        statement = (
            select(RegressionCaseRecord)
            .where(RegressionCaseRecord.case_id == case_id)
            .order_by(RegressionCaseRecord.case_version.desc())
            .limit(1)
        )
        record = await self._session.scalar(statement)
        return self._from_record(record) if record is not None else None

    async def case_version(self, case_id: UUID, case_version: int) -> StoredCase | None:
        statement = (
            select(RegressionCaseRecord)
            .where(RegressionCaseRecord.case_id == case_id)
            .where(RegressionCaseRecord.case_version == case_version)
        )
        record = await self._session.scalar(statement)
        return self._from_record(record) if record is not None else None

    async def list_latest_cases(self) -> tuple[StoredCase, ...]:
        latest_versions = (
            select(
                RegressionCaseRecord.case_id,
                func.max(RegressionCaseRecord.case_version).label("max_version"),
            )
            .group_by(RegressionCaseRecord.case_id)
            .subquery()
        )
        statement = (
            select(RegressionCaseRecord)
            .join(
                latest_versions,
                and_(
                    RegressionCaseRecord.case_id == latest_versions.c.case_id,
                    RegressionCaseRecord.case_version == latest_versions.c.max_version,
                ),
            )
            .order_by(RegressionCaseRecord.case_id)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(self._from_record(record) for record in records)

    async def insert_version(self, stored_case: StoredCase) -> StoredCase | None:
        """This method inserts one immutable case version.

        If a concurrent transaction already stored the same case version or
        the same content hash, this method rolls back and returns ``None``.
        """
        record = RegressionCaseRecord(
            id=uuid4(),
            case_id=stored_case.case_id,
            case_version=stored_case.case_version,
            source_type=stored_case.source_type,
            scenario_id=stored_case.scenario_id,
            bundle_content_hash=stored_case.bundle_content_hash,
            source_platform=stored_case.source_platform,
            source_trace_id=stored_case.source_trace_id,
            source_url=stored_case.source_url,
            evidence_content_hash=stored_case.evidence_content_hash,
            configuration_version=stored_case.configuration_version,
            bundle_json=stored_case.bundle_json,
            created_at=stored_case.created_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            return None
        return stored_case
