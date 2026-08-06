"""This module stores trace evidence idempotently with provenance and versions."""

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from app.domain.evidence.errors import InvalidEvidence
from app.domain.evidence.models import stable_evidence_id
from app.domain.evidence.schemas import TraceEvidence, compute_content_hash
from app.domain.evidence.store import EvidenceStore, StoredImport


class ImportStatus(StrEnum):
    """This enum defines the outcome of one evidence import."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    UPDATED = "updated"


class ImportResult(BaseModel):
    """This class stores the result of one evidence import."""

    status: ImportStatus
    evidence_id: UUID
    import_version: int
    content_hash: str
    source_platform: str
    source_trace_id: str


class TraceImportService:
    """This class imports evidence without creating duplicates.

    Reimporting unchanged evidence returns the existing row.
    Changed evidence creates a visible new import version for the same trace.
    """

    def __init__(self, store: EvidenceStore) -> None:
        self._store = store

    async def import_evidence(
        self,
        evidence: TraceEvidence,
        imported_at: datetime | None = None,
    ) -> ImportResult:
        """This method stores one piece of evidence and returns its import result."""
        if not evidence.events:
            raise InvalidEvidence(message="evidence has no events")
        content_hash = compute_content_hash(evidence)
        source_platform = evidence.source.platform
        source_trace_id = evidence.source.trace_id
        evidence_id = stable_evidence_id(evidence.source)

        await self._store.lock_evidence(evidence_id)

        existing = await self._store.find_exact_import(
            evidence_id=evidence_id,
            content_hash=content_hash,
        )
        if existing is not None:
            return ImportResult(
                status=ImportStatus.UNCHANGED,
                evidence_id=existing.evidence_id,
                import_version=existing.import_version,
                content_hash=existing.content_hash,
                source_platform=existing.source_platform,
                source_trace_id=existing.source_trace_id,
            )

        next_version = await self._store.latest_import_version(evidence_id) + 1
        stored_payload = evidence.model_dump(mode="json")
        stored_payload["evidence_id"] = str(evidence_id)
        stored_import = StoredImport(
            evidence_id=evidence_id,
            import_version=next_version,
            content_hash=content_hash,
            source_platform=source_platform,
            source_trace_id=source_trace_id,
            source_project=evidence.source.project,
            outcome=evidence.outcome.value,
            reason_code=evidence.reason_code,
            scenario_id=evidence.scenario_id,
        )
        inserted = await self._store.save_import(
            stored_import,
            schema_version=evidence.schema_version,
            source_url=evidence.source.url,
            workflow_version=evidence.workflow_version,
            evidence_json=stored_payload,
            imported_at=imported_at or datetime.now(timezone.utc),
        )
        if not inserted:
            raced = await self._store.find_exact_import(
                evidence_id=evidence_id,
                content_hash=content_hash,
            )
            if raced is not None:
                return ImportResult(
                    status=ImportStatus.UNCHANGED,
                    evidence_id=raced.evidence_id,
                    import_version=raced.import_version,
                    content_hash=raced.content_hash,
                    source_platform=raced.source_platform,
                    source_trace_id=raced.source_trace_id,
                )
            raise InvalidEvidence(message="trace import version conflicted; retry the import")
        status = ImportStatus.CREATED if next_version == 1 else ImportStatus.UPDATED
        return ImportResult(
            status=status,
            evidence_id=evidence_id,
            import_version=next_version,
            content_hash=content_hash,
            source_platform=source_platform,
            source_trace_id=source_trace_id,
        )
