"""Public schemas for failure candidates, groups, feedback, and review.

These schemas are vendor-neutral.  Source trace identity and event IDs remain
attached to every proposed label so later case generation can require a human
decision without reading a provider-specific payload.
"""

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.evidence.schemas import TraceEvidence, TraceSourceRef

FAILURE_DATASET_SCHEMA_VERSION = "1.0.0"
FAILURE_FEATURE_SCHEMA_VERSION = "1.0.0"
FAILURE_GROUPING_ALGORITHM_VERSION = "deterministic-dbscan-v1"

FeatureValue = bool | int | float | str


class FailureKind(StrEnum):
    """The explainable failure classes used by the Phase 6 baseline."""

    ROUTING = "routing"
    RETRIEVAL = "retrieval"
    TOOL = "tool"
    GENERATION = "generation"
    POLICY = "policy"
    INFRASTRUCTURE = "infrastructure"


class TraceLabel(BaseModel):
    """The expected label attached to one canonical dataset trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_id: str = Field(min_length=1, max_length=200)
    label: FailureKind | None = None
    source: str = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class FailureDatasetManifest(BaseModel):
    """A versioned manifest for the labeled canonical trace set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = FAILURE_DATASET_SCHEMA_VERSION
    dataset_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    dataset_version: int = Field(ge=1)
    trace_schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    labels: tuple[TraceLabel, ...] = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FailureDataset(BaseModel):
    """The canonical traces and their expected labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: FailureDatasetManifest
    traces: tuple[TraceEvidence, ...] = Field(min_length=1)


class FailureCandidate(BaseModel):
    """One explainable predicted failure linked to canonical event evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: UUID
    evidence_id: UUID
    source: TraceSourceRef
    predicted_kind: FailureKind
    features: dict[str, FeatureValue]
    evidence_event_ids: tuple[str, ...] = Field(min_length=1)
    feedback_ids: tuple[str, ...] = ()
    feature_schema_version: str = FAILURE_FEATURE_SCHEMA_VERSION
    dataset_version: int | None = Field(default=None, ge=1)


class FeedbackAnnotation(BaseModel):
    """Reviewer feedback imported from an annotation provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    annotation_id: str = Field(min_length=1, max_length=200)
    source_platform: str = Field(min_length=1, max_length=50)
    source_project: str | None = Field(default=None, max_length=200)
    trace_id: str = Field(min_length=1, max_length=200)
    event_id: str | None = Field(default=None, max_length=200)
    label: str = Field(min_length=1, max_length=100)
    score: float | None = None
    comment: str | None = Field(default=None, max_length=2000)
    reviewer: str | None = Field(default=None, max_length=200)
    annotated_at: datetime
    source_url: str | None = Field(default=None, max_length=2000)
    revision: int = Field(default=1, ge=1)
    correction_of: str | None = Field(default=None, max_length=200)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FeedbackImportStatus(StrEnum):
    """The result of importing one annotation revision."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    CORRECTED = "corrected"


class FeedbackImportResult(BaseModel):
    """The idempotent result returned by annotation import."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: FeedbackImportStatus
    annotation_id: str
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProposalStatus(StrEnum):
    """The lifecycle state of one proposed failure group."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    """The only human decisions that can create labeled truth."""

    CONFIRM = "confirm"
    CORRECT = "correct"
    REJECT = "reject"


class FailureGroupProposal(BaseModel):
    """A deterministic group proposal awaiting human review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID
    group_id: UUID
    proposal_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_id: str = Field(min_length=1, max_length=100)
    dataset_version: int = Field(ge=1)
    algorithm_version: str = Field(min_length=1, max_length=100)
    predicted_kind: FailureKind
    candidate_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_event_ids: dict[str, tuple[str, ...]]
    shared_features: dict[str, FeatureValue]
    status: ProposalStatus = ProposalStatus.PROPOSED
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    review_reason: str | None = None
    corrected_kind: FailureKind | None = None

    @model_validator(mode="after")
    def validate_review(self) -> "FailureGroupProposal":
        if self.status is ProposalStatus.PROPOSED:
            if any(
                value is not None
                for value in (self.reviewed_at, self.reviewed_by, self.corrected_kind)
            ):
                raise ValueError("a proposed group cannot have review provenance")
        elif not self.reviewed_by or self.reviewed_at is None or not self.review_reason:
            raise ValueError("reviewed groups require reviewer, timestamp, and reason")
        if self.status is ProposalStatus.CORRECTED and self.corrected_kind is None:
            raise ValueError("corrected groups require a corrected failure kind")
        return self


class FailureGroupReview(BaseModel):
    """One immutable audit record for a proposal decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: UUID
    proposal_id: UUID
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    reviewed_at: datetime
    corrected_kind: FailureKind | None = None
    source_evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_event_ids: dict[str, tuple[str, ...]]
    algorithm_version: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_decision(self) -> "FailureGroupReview":
        if self.decision is ReviewDecision.CORRECT and self.corrected_kind is None:
            raise ValueError("a correct decision requires a corrected failure kind")
        if self.decision is not ReviewDecision.CORRECT and self.corrected_kind is not None:
            raise ValueError("only a correct decision may include a corrected failure kind")
        return self


class ConfirmedFailureGroup(BaseModel):
    """The Phase 7 boundary: only this schema may build a regression case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID
    group_id: UUID
    failure_kind: FailureKind
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_event_ids: dict[str, tuple[str, ...]]
    review: FailureGroupReview
    dataset_id: str
    dataset_version: int
    algorithm_version: str


class FailureGroupingMetrics(BaseModel):
    """Deterministic coverage metrics emitted with grouping artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_count: int = Field(ge=0)
    grouped_candidate_count: int = Field(ge=0)
    outlier_count: int = Field(ge=0)
    group_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)


class FailureGroupResult(BaseModel):
    """The output of the deterministic grouping baseline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm_version: str = FAILURE_GROUPING_ALGORITHM_VERSION
    dataset_id: str
    dataset_version: int = Field(ge=1)
    configuration: dict[str, float | int | str]
    groups: tuple[tuple[FailureCandidate, ...], ...]
    outliers: tuple[FailureCandidate, ...]
    stable_group_ids: tuple[UUID, ...]
    metrics: FailureGroupingMetrics


def content_hash(payload: object) -> str:
    """Return the stable hash used by versioned failure artifacts."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode()).hexdigest()
