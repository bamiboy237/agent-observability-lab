"""This module provides an in-memory regression case repository for unit tests."""

from uuid import UUID

from app.domain.regression.repository import StoredCase


class InMemoryRegressionCaseRepository:
    def __init__(self) -> None:
        self.rows: list[StoredCase] = []

    async def latest_case(self, case_id: UUID) -> StoredCase | None:
        matching = [row for row in self.rows if row.case_id == case_id]
        return max(matching, key=lambda row: row.case_version) if matching else None

    async def case_version(self, case_id: UUID, case_version: int) -> StoredCase | None:
        for row in self.rows:
            if row.case_id == case_id and row.case_version == case_version:
                return row
        return None

    async def list_latest_cases(self) -> tuple[StoredCase, ...]:
        latest: dict[UUID, StoredCase] = {}
        for row in self.rows:
            current = latest.get(row.case_id)
            if current is None or row.case_version > current.case_version:
                latest[row.case_id] = row
        return tuple(latest[case_id] for case_id in sorted(latest))

    async def insert_version(self, stored_case: StoredCase) -> StoredCase | None:
        duplicate = any(
            row.case_id == stored_case.case_id
            and (
                row.case_version == stored_case.case_version
                or row.bundle_content_hash == stored_case.bundle_content_hash
            )
            for row in self.rows
        )
        if duplicate:
            return None
        self.rows.append(stored_case)
        return stored_case
