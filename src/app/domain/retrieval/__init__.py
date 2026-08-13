"""Deterministic, measured retrieval for support policy evidence."""

from app.domain.retrieval.chunking import DeterministicChunker, chunk_document
from app.domain.retrieval.contracts import (
    DocumentChunk,
    EmbeddingProvider,
    RetrievalHit,
    Retriever,
    SourceDocument,
)
from app.domain.retrieval.embeddings import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from app.domain.retrieval.fusion import FusedRetriever, reciprocal_rank_fusion

__all__ = [
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL",
    "DeterministicChunker",
    "DocumentChunk",
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "FusedRetriever",
    "OpenAIEmbeddingProvider",
    "RetrievalHit",
    "Retriever",
    "SourceDocument",
    "chunk_document",
    "reciprocal_rank_fusion",
]
