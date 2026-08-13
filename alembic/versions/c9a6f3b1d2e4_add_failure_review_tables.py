"""Add Phase 6 feedback and failure review tables.

Revision ID: c9a6f3b1d2e4
Revises: 4bb75b530756
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9a6f3b1d2e4"
down_revision: str | Sequence[str] | None = "4bb75b530756"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "failure_feedback_annotations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("annotation_id", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_platform", sa.String(length=50), nullable=False),
        sa.Column("source_project", sa.String(length=200), nullable=True),
        sa.Column("trace_id", sa.String(length=200), nullable=False),
        sa.Column("event_id", sa.String(length=200), nullable=True),
        sa.Column("annotation_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("annotation_id", "revision", name="uq_failure_feedback_revision"),
        sa.UniqueConstraint("annotation_id", "content_hash", name="uq_failure_feedback_hash"),
    )
    op.create_index(
        "ix_failure_feedback_trace",
        "failure_feedback_annotations",
        ["source_platform", "trace_id"],
        unique=False,
    )
    op.create_table(
        "failure_group_proposals",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("dataset_id", sa.String(length=100), nullable=False),
        sa.Column("dataset_version", sa.Integer(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=100), nullable=False),
        sa.Column("predicted_kind", sa.String(length=30), nullable=False),
        sa.Column("candidate_ids_json", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_ids_json", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_event_ids_json", postgresql.JSONB(), nullable=False),
        sa.Column("shared_features_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="proposed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=200), nullable=True),
        sa.Column("review_reason", sa.String(length=2000), nullable=True),
        sa.Column("corrected_kind", sa.String(length=30), nullable=True),
        sa.CheckConstraint(
            "status IN ('proposed', 'confirmed', 'corrected', 'rejected')",
            name="ck_failure_group_proposal_status",
        ),
        sa.PrimaryKeyConstraint("proposal_id"),
        sa.UniqueConstraint("proposal_fingerprint", name="uq_failure_group_proposal_fingerprint"),
    )
    op.create_index(
        "ix_failure_group_proposals_status",
        "failure_group_proposals",
        ["status"],
        unique=False,
    )
    op.create_table(
        "failure_group_reviews",
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corrected_kind", sa.String(length=30), nullable=True),
        sa.Column("source_evidence_ids_json", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_event_ids_json", postgresql.JSONB(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("review_id"),
        sa.UniqueConstraint("proposal_id", name="uq_failure_group_one_review"),
    )
    op.create_index(
        "ix_failure_group_reviews_proposal",
        "failure_group_reviews",
        ["proposal_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_failure_group_reviews_proposal", table_name="failure_group_reviews")
    op.drop_table("failure_group_reviews")
    op.drop_index("ix_failure_group_proposals_status", table_name="failure_group_proposals")
    op.drop_table("failure_group_proposals")
    op.drop_index("ix_failure_feedback_trace", table_name="failure_feedback_annotations")
    op.drop_table("failure_feedback_annotations")
