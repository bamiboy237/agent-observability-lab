"""This module defines the vendor-neutral trace source contract.

A trace source fetches one selected trace or an explicit bounded cohort.
Authentication, pagination, and provider errors stay inside adapters.
Sources translate provider failures into typed :mod:`app.domain.evidence.errors`.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.evidence.schemas import TraceEvidence

MAX_COHORT_LIMIT = 50


class TraceQuery(BaseModel):
    """This class stores an explicit bounded cohort selection.

    Every filter is optional. ``limit`` is always bounded.
    A source that cannot record a filter field returns no matches for it.
    """

    model_config = ConfigDict(extra="forbid")

    workflow: str | None = Field(default=None, max_length=100)
    environment: str | None = Field(default=None, max_length=100)
    model_name: str | None = Field(default=None, max_length=200)
    config_version: str | None = Field(default=None, max_length=100)
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=1, ge=1, le=MAX_COHORT_LIMIT)

    @model_validator(mode="after")
    def validate_time_window(self) -> "TraceQuery":
        """This method rejects an inverted time window."""
        if self.since is not None and self.until is not None and self.until < self.since:
            raise ValueError("until must not be earlier than since")
        return self


class TraceSource(Protocol):
    """This protocol defines the common operations of every trace source.

    ``fetch_trace`` returns one selected trace as normalized evidence.
    ``fetch_traces`` returns an explicit bounded cohort for one query.
    """

    async def fetch_trace(self, source_trace_id: str) -> TraceEvidence: ...

    async def fetch_traces(self, query: TraceQuery) -> list[TraceEvidence]: ...


def evidence_matches_query(evidence: TraceEvidence, query: TraceQuery) -> bool:
    """This function applies cohort filters to one piece of evidence.

    Sources share this function so every provider filters identically.
    A source that cannot record ``environment`` returns no matches for it.
    """
    if query.workflow is not None and evidence.workflow != query.workflow:
        return False
    if query.environment is not None and evidence.environment != query.environment:
        return False
    if query.model_name is not None:
        if evidence.model is None or evidence.model.name != query.model_name:
            return False
    if query.config_version is not None and evidence.workflow_version != query.config_version:
        return False
    root = next((event for event in evidence.events if event.parent_id is None), None)
    if root is not None:
        if query.since is not None and root.start_time < query.since:
            return False
        if query.until is not None and root.start_time > query.until:
            return False
    return True
