"""This module provides an in-memory regression suite repository for unit tests."""

from uuid import UUID

from app.domain.suite.repository import StoredSuite


class InMemorySuiteRepository:
    def __init__(self) -> None:
        self.rows: list[StoredSuite] = []

    async def latest_suite(self, suite_id: UUID) -> StoredSuite | None:
        matching = [row for row in self.rows if row.suite_id == suite_id]
        return max(matching, key=lambda row: row.suite_version) if matching else None

    async def suite_version(self, suite_id: UUID, suite_version: int) -> StoredSuite | None:
        for row in self.rows:
            if row.suite_id == suite_id and row.suite_version == suite_version:
                return row
        return None

    async def list_latest_suites(self) -> tuple[StoredSuite, ...]:
        latest: dict[UUID, StoredSuite] = {}
        for row in self.rows:
            current = latest.get(row.suite_id)
            if current is None or row.suite_version > current.suite_version:
                latest[row.suite_id] = row
        return tuple(latest[suite_id] for suite_id in sorted(latest))

    async def insert_version(self, stored_suite: StoredSuite) -> StoredSuite | None:
        duplicate = any(
            row.suite_id == stored_suite.suite_id
            and (
                row.suite_version == stored_suite.suite_version
                or row.members_hash == stored_suite.members_hash
            )
            for row in self.rows
        )
        if duplicate:
            return None
        self.rows.append(stored_suite)
        return stored_suite
