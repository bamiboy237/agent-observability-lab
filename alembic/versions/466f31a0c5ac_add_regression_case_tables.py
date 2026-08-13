"""This migration adds tables for the saved regression case library.

Revision ID: 466f31a0c5ac
Revises: b7e1f4c8d2a6
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "466f31a0c5ac"
down_revision: str | Sequence[str] | None = "b7e1f4c8d2a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "regression_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("scenario_id", sa.String(length=100), nullable=False),
        sa.Column("bundle_content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_platform", sa.String(length=50), nullable=True),
        sa.Column("source_trace_id", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("evidence_content_hash", sa.String(length=64), nullable=True),
        sa.Column("configuration_version", sa.String(length=50), nullable=True),
        sa.Column("bundle_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('incident', 'suspicious_success', 'designed_edge_case', "
            "'model_comparison')",
            name="ck_regression_cases_source_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id",
            "case_version",
            name="uq_regression_cases_case_version",
        ),
        sa.UniqueConstraint(
            "case_id",
            "bundle_content_hash",
            name="uq_regression_cases_case_hash",
        ),
    )
    op.create_index(
        "ix_regression_cases_case_id",
        "regression_cases",
        ["case_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_regression_cases_case_id", table_name="regression_cases")
    op.drop_table("regression_cases")
