"""PostgreSQL proof for the Phase 3 retrieval corpus and retrievers."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.config import Settings
from app.db import get_session_factory
from app.domain.retrieval.chunking import DeterministicChunker
from app.domain.retrieval.contracts import SourceDocument
from app.domain.retrieval.embeddings import FakeEmbeddingProvider
from app.domain.retrieval.evaluate import evaluate_retriever, load_dataset
from app.domain.retrieval.models import RetrievalChunk
from app.domain.retrieval.storage import (
    KeywordRetriever,
    RetrievalIngestionService,
    VectorRetriever,
)
from app.domain.support.seed import POLICY_DOCUMENTS


@pytest.fixture(scope="module", autouse=True)
def apply_retrieval_migrations() -> None:
    try:
        Settings()  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL is required for retrieval integration tests")
    command.upgrade(Config("alembic.ini"), "head")


def seeded_document(*, version: str = "2026-07-30", content: str | None = None) -> SourceDocument:
    seed = POLICY_DOCUMENTS[0]
    return SourceDocument(
        document_id=seed["id"],
        slug=seed["slug"],
        version=version,
        title=seed["title"],
        content=content or seed["content"],
        source_metadata={"source": "seed"},
    )


async def cleanup_document(document: SourceDocument) -> None:
    async with get_session_factory().begin() as session:
        await session.execute(
            delete(RetrievalChunk).where(RetrievalChunk.document_id == document.document_id)
        )


@pytest.mark.integration
async def test_ingestion_is_idempotent_and_preserves_versions() -> None:
    document = seeded_document()
    changed = seeded_document(
        version="2026-08-01",
        content=document.content + " Appeals require review.",
    )
    await cleanup_document(document)
    try:
        provider = FakeEmbeddingProvider()
        async with get_session_factory().begin() as session:
            service = RetrievalIngestionService(
                session,
                provider,
                chunker=DeterministicChunker(chunk_size=40, overlap=8),
            )
            first = await service.ingest(document)
            second = await service.ingest(document)
            third = await service.ingest(changed)

        assert first == second
        async with get_session_factory()() as session:
            rows = (
                await session.execute(
                    select(RetrievalChunk)
                    .where(RetrievalChunk.document_id == document.document_id)
                    .order_by(RetrievalChunk.document_version, RetrievalChunk.ordinal)
                )
            ).scalars().all()
        assert len(rows) == len(first) + len(third)
        assert {row.document_version for row in rows} == {document.version, changed.version}
        assert len({row.chunk_id for row in rows}) == len(rows)
    finally:
        await cleanup_document(document)


@pytest.mark.integration
async def test_keyword_and_vector_retrievers_return_exact_stored_chunks() -> None:
    document = seeded_document()
    await cleanup_document(document)
    try:
        async with get_session_factory().begin() as session:
            await RetrievalIngestionService(
                session,
                FakeEmbeddingProvider(),
                chunker=DeterministicChunker(chunk_size=160, overlap=32),
            ).ingest(document)
        async with get_session_factory()() as session:
            keyword = await KeywordRetriever(session).search("refund within 30 days")
            vector = await VectorRetriever(session, FakeEmbeddingProvider()).search("refund policy")
        assert keyword
        assert vector
        assert keyword[0].source == "keyword"
        assert vector[0].source == "vector"
        source_text = " ".join(document.content.split())
        assert keyword[0].text in source_text
        assert vector[0].text in source_text
    finally:
        await cleanup_document(document)


@pytest.mark.integration
async def test_versioned_retrieval_evaluation_writes_measured_metrics() -> None:
    document = seeded_document()
    await cleanup_document(document)
    try:
        async with get_session_factory().begin() as session:
            await RetrievalIngestionService(session, FakeEmbeddingProvider()).ingest(document)
        examples = load_dataset(Path("tests/fixtures/retrieval_eval_v1.jsonl"))
        async with get_session_factory()() as session:
            metrics, failures = await evaluate_retriever(KeywordRetriever(session), examples)
        assert metrics["query_count"] == 20
        assert float(metrics["recall_at_5"]) >= 0.80
        assert len(failures) <= 4
    finally:
        await cleanup_document(document)
