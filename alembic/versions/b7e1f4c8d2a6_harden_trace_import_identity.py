"""This migration makes trace identity and import versions unambiguous.

Revision ID: b7e1f4c8d2a6
Revises: a3d9c2b1e4f5
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7e1f4c8d2a6"
down_revision: str | Sequence[str] | None = "a3d9c2b1e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_trace_imports_platform_trace_hash",
        "trace_imports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_trace_imports_evidence_hash",
        "trace_imports",
        ["evidence_id", "content_hash"],
    )
    op.create_unique_constraint(
        "uq_trace_imports_evidence_version",
        "trace_imports",
        ["evidence_id", "import_version"],
    )
    op.drop_index("ix_trace_imports_platform_trace", table_name="trace_imports")
    op.create_index(
        "ix_trace_imports_source",
        "trace_imports",
        ["source_platform", "source_project", "source_trace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_trace_imports_source", table_name="trace_imports")
    op.create_index(
        "ix_trace_imports_platform_trace",
        "trace_imports",
        ["source_platform", "source_trace_id"],
        unique=False,
    )
    op.drop_constraint(
        "uq_trace_imports_evidence_version",
        "trace_imports",
        type_="unique",
    )
    op.drop_constraint(
        "uq_trace_imports_evidence_hash",
        "trace_imports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_trace_imports_platform_trace_hash",
        "trace_imports",
        ["source_platform", "source_trace_id", "content_hash"],
    )
