"""This migration establishes the baseline revision.

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
    """This function creates the initial revision without tables for product data."""


def downgrade() -> None:
    """This function returns the database to a schema that excludes product tables."""
