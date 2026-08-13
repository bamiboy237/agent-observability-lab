"""Transactional persistence and retrieval queries for indexed chunks."""

import re
from typing import Any

from sqlalchemy import Float, cast, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.retrieval.chunking import DeterministicChunker
from app.domain.retrieval.contracts import (
    DocumentChunk,
    EmbeddingProvider,
    RetrievalHit,
    SourceDocument,
)
from app.domain.retrieval.embeddings import DEFAULT_EMBEDDING_DIMENSION
from app.domain.retrieval.errors import EmbeddingDimensionMismatch, EmbeddingProviderUnavailable
from app.domain.retrieval.models import RetrievalChunk, Vector


def _as_source_document(document: SourceDocument | Any) -> SourceDocument:
    if isinstance(document, SourceDocument):
        return document
    return SourceDocument(
        document_id=document.id,
        slug=document.slug,
        version=document.version,
        title=document.title,
        content=document.content,
        source_metadata={"source": "support.policy_documents"},
    )


class RetrievalIngestionService:
    """Build and transactionally upsert a complete versioned corpus document."""

    def __init__(
        self,
        session: AsyncSession,
        provider: EmbeddingProvider,
        *,
        chunker: DeterministicChunker | None = None,
    ) -> None:
        self._session = session
        self._provider = provider
        self._chunker = chunker or DeterministicChunker()

    async def ingest(self, document: SourceDocument | Any) -> tuple[DocumentChunk, ...]:
        source = _as_source_document(document)
        chunks = tuple(self._chunker.chunk(source))
        try:
            vectors = await self._provider.embed([chunk.text for chunk in chunks])
        except Exception as error:
            if isinstance(error, EmbeddingDimensionMismatch):
                raise
            raise EmbeddingProviderUnavailable() from error
        if len(vectors) != len(chunks):
            raise EmbeddingProviderUnavailable()
        for vector in vectors:
            if len(vector) != self._provider.dimension:
                raise EmbeddingDimensionMismatch(self._provider.dimension, len(vector))
        if self._provider.dimension != DEFAULT_EMBEDDING_DIMENSION:
            # The storage schema has one configured model dimension.  Fake
            # providers are supported by a separate in-memory retriever; the
            # Postgres corpus stays compatible with the pinned OpenAI model.
            raise EmbeddingDimensionMismatch(DEFAULT_EMBEDDING_DIMENSION, self._provider.dimension)

        rows = [
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "document_slug": chunk.document_slug,
                "document_version": chunk.document_version,
                "title": chunk.title,
                "ordinal": chunk.ordinal,
                "text": chunk.text,
                "embedding": vector,
                "content_hash": chunk.content_hash,
                "source_metadata": chunk.source_metadata,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if rows:
            statement = insert(RetrievalChunk).values(rows)
            statement = statement.on_conflict_do_update(
                index_elements=[RetrievalChunk.chunk_id],
                set_={
                    "text": statement.excluded.text,
                    "embedding": statement.excluded.embedding,
                    "content_hash": statement.excluded.content_hash,
                    "source_metadata": statement.excluded.source_metadata,
                },
            )
            # A savepoint ensures callers can recover the outer transaction
            # while a failed database write cannot leave a partial document.
            async with self._session.begin_nested():
                await self._session.execute(statement)
        return chunks


def _hit(row: Any, *, source: str, score: float, rank: int, corpus_version: str) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_version=row.document_version,
        text=row.text,
        score=float(score),
        source=source,  # type: ignore[arg-type]
        corpus_version=corpus_version,
        rank=rank,
    )


class KeywordRetriever:
    """PostgreSQL full-text retriever with parameterized query construction."""

    def __init__(self, session: AsyncSession, *, corpus_version: str = "policy-v1") -> None:
        self._session = session
        self.corpus_version = corpus_version

    async def search(self, query: str, limit: int = 5) -> list[RetrievalHit]:
        if not query.strip() or limit < 1:
            return []
        terms = re.findall(r"[A-Za-z0-9]+", query)
        if not terms:
            return []
        # OR semantics make natural-language questions useful when they
        # contain stop words or concepts absent from a short policy chunk.
        # Tokens are extracted to alphanumerics before being passed as a
        # bound parameter, so user text cannot change SQL structure.
        ts_query = func.to_tsquery("english", " | ".join(terms))
        score = func.ts_rank_cd(RetrievalChunk.search_vector, ts_query)
        statement = (
            select(RetrievalChunk, score.label("score"))
            .where(RetrievalChunk.search_vector.op("@@")(ts_query))
            .order_by(score.desc(), RetrievalChunk.chunk_id)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            _hit(
                row.RetrievalChunk,
                source="keyword",
                score=row.score,
                rank=index,
                corpus_version=self.corpus_version,
            )
            for index, row in enumerate(rows, start=1)
        ]


class VectorRetriever:
    """Cosine-distance PostgreSQL retriever using the shared embedding contract."""

    def __init__(
        self,
        session: AsyncSession,
        provider: EmbeddingProvider,
        *,
        corpus_version: str = "policy-v1",
    ) -> None:
        self._session = session
        self._provider = provider
        self.corpus_version = corpus_version

    async def search(self, query: str, limit: int = 5) -> list[RetrievalHit]:
        if not query.strip() or limit < 1:
            return []
        try:
            vector = await self._provider.embed_one(query)
        except Exception as error:
            if isinstance(error, EmbeddingDimensionMismatch):
                raise
            raise EmbeddingProviderUnavailable() from error
        if len(vector) != self._provider.dimension:
            raise EmbeddingDimensionMismatch(self._provider.dimension, len(vector))
        if self._provider.dimension != DEFAULT_EMBEDDING_DIMENSION:
            raise EmbeddingDimensionMismatch(DEFAULT_EMBEDDING_DIMENSION, self._provider.dimension)
        raw_distance = RetrievalChunk.embedding.op("<=>")(
            literal(vector, type_=Vector(self._provider.dimension))
        )
        distance: Any = cast(raw_distance, Float)
        statement = (
            select(RetrievalChunk, distance.label("distance"))
            .order_by(distance.asc(), RetrievalChunk.chunk_id)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            _hit(
                row.RetrievalChunk,
                source="vector",
                score=max(0.0, min(1.0, 1.0 - float(row.distance))),
                rank=index,
                corpus_version=self.corpus_version,
            )
            for index, row in enumerate(rows, start=1)
        ]
