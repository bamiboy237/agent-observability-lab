"""Add the versioned pgvector retrieval corpus."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision: str = "9f7c2a1d5e4b"
down_revision: str | Sequence[str] | None = "c9a6f3b1d2e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class VectorType(UserDefinedType):
    """Migration-only declaration for the pgvector column."""

    def get_col_spec(self, **_: object) -> str:
        return "VECTOR(1536)"


def upgrade() -> None:
    # The application intentionally targets PostgreSQL with pgvector.  The
    # Docker and CI services use the pgvector image; hosted Postgres must have
    # the extension enabled before this migration runs.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "retrieval_chunks",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_slug", sa.String(length=200), nullable=False),
        sa.Column("document_version", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", VectorType(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(
        "ix_retrieval_chunks_document_id",
        "retrieval_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_retrieval_chunks_document_version",
        "retrieval_chunks",
        ["document_id", "document_version"],
        unique=False,
    )
    op.create_index(
        "ix_retrieval_chunks_search_vector",
        "retrieval_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.execute(
        "CREATE INDEX ix_retrieval_chunks_embedding ON retrieval_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_retrieval_chunks_embedding")
    op.drop_index("ix_retrieval_chunks_search_vector", table_name="retrieval_chunks")
    op.drop_index("ix_retrieval_chunks_document_version", table_name="retrieval_chunks")
    op.drop_index("ix_retrieval_chunks_document_id", table_name="retrieval_chunks")
    op.drop_table("retrieval_chunks")
