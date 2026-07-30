"""Establish the baseline migration revision.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-30
"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial revision without product tables."""


def downgrade() -> None:
    """Return to the pre-product schema."""
