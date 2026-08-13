"""This migration adds tables for the versioned regression suite library.

Revision ID: 4bb75b530756
Revises: 466f31a0c5ac
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4bb75b530756"
down_revision: str | Sequence[str] | None = "466f31a0c5ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "regression_suites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("suite_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("members_hash", sa.String(length=64), nullable=False),
        sa.Column("members_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "suite_id",
            "suite_version",
            name="uq_regression_suites_suite_version",
        ),
        sa.UniqueConstraint(
            "suite_id",
            "members_hash",
            name="uq_regression_suites_members_hash",
        ),
    )
    op.create_index(
        "ix_regression_suites_suite_id",
        "regression_suites",
        ["suite_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_regression_suites_suite_id", table_name="regression_suites")
    op.drop_table("regression_suites")
