"""This module provides an in-memory evidence store for unit tests."""

from datetime import datetime
from uuid import UUID

from app.domain.evidence.store import StoredImport


class InMemoryEvidenceStore:
    def __init__(self) -> None:
        self.rows: list[StoredImport] = []
        self._saved_payloads: list[tuple[StoredImport, dict[str, object]]] = []

    async def lock_evidence(self, evidence_id: UUID) -> None:
        return None

    async def find_exact_import(
        self,
        *,
        evidence_id: UUID,
        content_hash: str,
    ) -> StoredImport | None:
        for row in self.rows:
            if (
                row.evidence_id == evidence_id and row.content_hash == content_hash
            ):
                return row
        return None

    async def latest_import_version(self, evidence_id: UUID) -> int:
        versions = [row.import_version for row in self.rows if row.evidence_id == evidence_id]
        return max(versions) if versions else 0

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
        duplicate = any(
            row.source_platform == stored_import.source_platform
            and row.source_trace_id == stored_import.source_trace_id
            and row.content_hash == stored_import.content_hash
            for row in self.rows
        )
        if duplicate:
            return False
        self.rows.append(stored_import)
        self._saved_payloads.append((stored_import, evidence_json))
        return True
