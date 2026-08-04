"""add policy documents

Revision ID: 4f51cd9c287d
Revises: 7ecfe203df28
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4f51cd9c287d"
down_revision: str | Sequence[str] | None = "7ecfe203df28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "slug",
            "version",
            name="uq_policy_documents_slug_version",
        ),
    )


def downgrade() -> None:
    op.drop_table("policy_documents")
