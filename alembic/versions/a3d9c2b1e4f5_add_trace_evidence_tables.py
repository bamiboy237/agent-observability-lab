"""This migration adds tables for imported trace evidence.

Revision ID: a3d9c2b1e4f5
Revises: 4f51cd9c287d
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3d9c2b1e4f5"
down_revision: str | Sequence[str] | None = "4f51cd9c287d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trace_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("import_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("source_platform", sa.String(length=50), nullable=False),
        sa.Column("source_project", sa.String(length=200), nullable=True),
        sa.Column("source_trace_id", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("scenario_id", sa.String(length=100), nullable=True),
        sa.Column("workflow_version", sa.String(length=50), nullable=True),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_platform",
            "source_trace_id",
            "content_hash",
            name="uq_trace_imports_platform_trace_hash",
        ),
    )
    op.create_index(
        "ix_trace_imports_evidence_id",
        "trace_imports",
        ["evidence_id"],
        unique=False,
    )
    op.create_index(
        "ix_trace_imports_platform_trace",
        "trace_imports",
        ["source_platform", "source_trace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_trace_imports_platform_trace", table_name="trace_imports")
    op.drop_index("ix_trace_imports_evidence_id", table_name="trace_imports")
    op.drop_table("trace_imports")
