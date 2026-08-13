"""SQLAlchemy persistence models for versioned retrieval chunks."""

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from sqlalchemy import JSON, Computed, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.db import Base


class Vector(UserDefinedType[Any]):
    """Small SQLAlchemy adapter for PostgreSQL's pgvector type.

    Keeping this type local avoids coupling the domain to a second ORM package.
    """

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        if dimension < 1:
            raise ValueError("vector dimension must be positive")
        self.dimension = dimension

    def get_col_spec(self, **_: Any) -> str:
        return f"VECTOR({self.dimension})"

    def bind_processor(self, dialect: Any) -> Any:
        def process(value: Sequence[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(str(float(item)) for item in value) + "]"

        return process

    def result_processor(self, dialect: Any, coltype: Any) -> Any:
        def process(value: object) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, str):
                return [float(item) for item in value.strip("[]").split(",") if item]
            values = cast(Sequence[float | str], value)
            return [float(item) for item in values]

        return process


class Tsvector(UserDefinedType[Any]):
    """SQLAlchemy type for PostgreSQL's generated full-text vector."""

    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "TSVECTOR"


class RetrievalChunk(Base):
    """One indexed document chunk and its reproducible source identity."""

    __tablename__ = "retrieval_chunks"
    __table_args__ = (
        Index("ix_retrieval_chunks_document_version", "document_id", "document_version"),
        Index("ix_retrieval_chunks_search_vector", "search_vector", postgresql_using="gin"),
        Index(
            "ix_retrieval_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    chunk_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    document_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    document_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    document_version: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str] = mapped_column(
        Tsvector(),
        Computed("to_tsvector('english', text)", persisted=True),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_metadata: Mapped[dict[str, str]] = mapped_column(JSONB().with_variant(JSON(), "sqlite"))
