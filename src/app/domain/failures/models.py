"""Database records for feedback and the human review lifecycle."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FeedbackAnnotationRecord(Base):
    """Immutable annotation revisions keyed by provider annotation identity."""

    __tablename__ = "failure_feedback_annotations"
    __table_args__ = (
        UniqueConstraint("annotation_id", "revision", name="uq_failure_feedback_revision"),
        UniqueConstraint("annotation_id", "content_hash", name="uq_failure_feedback_hash"),
        Index("ix_failure_feedback_trace", "source_platform", "trace_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    annotation_id: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    source_platform: Mapped[str] = mapped_column(String(50))
    source_project: Mapped[str | None] = mapped_column(String(200), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(200))
    event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    annotation_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class FailureGroupProposalRecord(Base):
    """One deterministic group proposal and its current review state."""

    __tablename__ = "failure_group_proposals"
    __table_args__ = (
        UniqueConstraint("proposal_fingerprint", name="uq_failure_group_proposal_fingerprint"),
        Index("ix_failure_group_proposals_status", "status"),
        CheckConstraint(
            "status IN ('proposed', 'confirmed', 'corrected', 'rejected')",
            name="ck_failure_group_proposal_status",
        ),
    )

    proposal_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    group_id: Mapped[UUID] = mapped_column(Uuid)
    proposal_fingerprint: Mapped[str] = mapped_column(String(64))
    dataset_id: Mapped[str] = mapped_column(String(100))
    dataset_version: Mapped[int] = mapped_column(Integer)
    algorithm_version: Mapped[str] = mapped_column(String(100))
    predicted_kind: Mapped[str] = mapped_column(String(30))
    candidate_ids_json: Mapped[list[str]] = mapped_column(JSONB)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSONB)
    evidence_event_ids_json: Mapped[dict[str, list[str]]] = mapped_column(JSONB)
    shared_features_json: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="proposed", server_default="proposed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    corrected_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)


class FailureGroupReviewRecord(Base):
    """Immutable audit record for one proposal review."""

    __tablename__ = "failure_group_reviews"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_failure_group_one_review"),
        Index("ix_failure_group_reviews_proposal", "proposal_id"),
    )

    review_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(Uuid)
    decision: Mapped[str] = mapped_column(String(20))
    reviewer: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(2000))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    corrected_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_evidence_ids_json: Mapped[list[str]] = mapped_column(JSONB)
    evidence_event_ids_json: Mapped[dict[str, list[str]]] = mapped_column(JSONB)
    algorithm_version: Mapped[str] = mapped_column(String(100))
