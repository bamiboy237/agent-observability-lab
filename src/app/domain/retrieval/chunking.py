"""Deterministic token-aware document chunking."""

from hashlib import sha256
from uuid import UUID, uuid5

from app.domain.retrieval.contracts import DocumentChunk, SourceDocument

CHUNK_NAMESPACE = UUID("35b6a2d7-0a3b-5f8d-9c3e-20d15ee66d37")
DEFAULT_CHUNK_SIZE = 160
DEFAULT_CHUNK_OVERLAP = 32


def _tokens(text: str) -> list[str]:
    """Split text into stable whitespace tokens."""
    return text.split()


class DeterministicChunker:
    """Split documents by explicit token size and overlap.

    This deliberately uses a small, documented whitespace tokenizer.  It has
    no provider dependency, so ingestion inputs can be reproduced offline.
    """

    def __init__(
        self,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be between zero and chunk_size - 1")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: SourceDocument) -> list[DocumentChunk]:
        """Return stable chunks in source order."""
        tokens = _tokens(document.content)
        if not tokens:
            return []
        step = self.chunk_size - self.overlap
        chunks: list[DocumentChunk] = []
        for ordinal, start in enumerate(range(0, len(tokens), step)):
            text = " ".join(tokens[start : start + self.chunk_size])
            if not text:
                break
            content_hash = sha256(text.encode("utf-8")).hexdigest()
            identity = (
                f"{document.document_id}|{document.slug}|{document.version}|"
                f"{ordinal}|{content_hash}"
            )
            chunks.append(
                DocumentChunk(
                    chunk_id=uuid5(CHUNK_NAMESPACE, identity),
                    document_id=document.document_id,
                    document_slug=document.slug,
                    document_version=document.version,
                    title=document.title,
                    ordinal=ordinal,
                    text=text,
                    content_hash=content_hash,
                    source_metadata=dict(document.source_metadata),
                )
            )
            if start + self.chunk_size >= len(tokens):
                break
        return chunks


def chunk_document(
    document: SourceDocument,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[DocumentChunk]:
    """Chunk one document with explicit deterministic settings."""
    return DeterministicChunker(chunk_size=chunk_size, overlap=overlap).chunk(document)
