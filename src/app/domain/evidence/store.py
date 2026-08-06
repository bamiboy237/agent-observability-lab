"""This module defines the persistence boundary for imported trace evidence."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.evidence.models import TraceImport


@dataclass(frozen=True)
class StoredImport:
    """This class stores the identity and provenance of one imported trace."""

    evidence_id: UUID
    import_version: int
    content_hash: str
    source_platform: str
    source_trace_id: str
    source_project: str | None
    outcome: str
    reason_code: str
    scenario_id: str | None


class EvidenceStore(Protocol):
    """This protocol defines the operations the import service needs."""

    async def lock_evidence(self, evidence_id: UUID) -> None: ...

    async def find_exact_import(
        self,
        *,
        evidence_id: UUID,
        content_hash: str,
    ) -> StoredImport | None: ...

    async def latest_import_version(self, evidence_id: UUID) -> int: ...

    async def save_import(
        self,
        stored_import: StoredImport,
        *,
        schema_version: str,
        source_url: str | None,
        workflow_version: str | None,
        evidence_json: dict[str, object],
        imported_at: datetime,
    ) -> bool: ...


class SqlAlchemyEvidenceStore:
    """This class persists trace imports through one SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_evidence(self, evidence_id: UUID) -> None:
        """This method serializes imports for one trace within the transaction."""
        lock_key = int.from_bytes(evidence_id.bytes[:8], byteorder="big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def find_exact_import(
        self,
        *,
        evidence_id: UUID,
        content_hash: str,
    ) -> StoredImport | None:
        statement = (
            select(TraceImport)
            .where(TraceImport.evidence_id == evidence_id)
            .where(TraceImport.content_hash == content_hash)
        )
        row = await self._session.scalar(statement)
        if row is None:
            return None
        return StoredImport(
            evidence_id=row.evidence_id,
            import_version=row.import_version,
            content_hash=row.content_hash,
            source_platform=row.source_platform,
            source_trace_id=row.source_trace_id,
            source_project=row.source_project,
            outcome=row.outcome,
            reason_code=row.reason_code,
            scenario_id=row.scenario_id,
        )

    async def latest_import_version(self, evidence_id: UUID) -> int:
        statement = select(func.max(TraceImport.import_version)).where(
            TraceImport.evidence_id == evidence_id
        )
        version = await self._session.scalar(statement)
        return int(version or 0)

    async def save_import(
        self,
        stored_import: StoredImport,
        *,
        schema_version: str,
        source_url: str | None,
        workflow_version: str | None,
        evidence_json: dict[str, object],
        imported_at: datetime,
    ) -> bool:
        """This method inserts one import row.

        If a concurrent import already inserted the same trace and hash,
        this method rolls back and returns ``False``.
        """
        row = TraceImport(
            evidence_id=stored_import.evidence_id,
            import_version=stored_import.import_version,
            schema_version=schema_version,
            source_platform=stored_import.source_platform,
            source_project=stored_import.source_project,
            source_trace_id=stored_import.source_trace_id,
            source_url=source_url,
            scenario_id=stored_import.scenario_id,
            workflow_version=workflow_version,
            outcome=stored_import.outcome,
            reason_code=stored_import.reason_code,
            content_hash=stored_import.content_hash,
            evidence_json=evidence_json,
            imported_at=imported_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            return False
        return True
