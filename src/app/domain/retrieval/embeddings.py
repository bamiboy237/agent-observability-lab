"""Embedding providers.

Only this module imports the OpenAI SDK.  The rest of the application depends
on :class:`EmbeddingProvider` and can use the deterministic fake in tests.
"""

from collections.abc import Sequence
from hashlib import sha256
from math import sqrt
from typing import Any

from openai import AsyncOpenAI

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSION = 1536


def _normalise(vector: list[float]) -> list[float]:
    magnitude = sqrt(sum(value * value for value in vector))
    return [value / magnitude for value in vector] if magnitude else vector


class FakeEmbeddingProvider:
    """A deterministic local embedding provider for tests and offline replay."""

    model = "fake-hash-v1"

    def __init__(self, dimension: int = DEFAULT_EMBEDDING_DIMENSION) -> None:
        if dimension < 2:
            raise ValueError("dimension must be at least 2")
        self.dimension = dimension

    def _embed_one(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        for token in text.casefold().split():
            digest = sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            values[index] += sign
        return _normalise(values)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    async def embed_one(self, text: str) -> list[float]:
        return self._embed_one(text)


class OpenAIEmbeddingProvider:
    """The sanctioned OpenAI embedding adapter with a pinned model contract."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        if model != DEFAULT_EMBEDDING_MODEL or dimension != DEFAULT_EMBEDDING_DIMENSION:
            raise ValueError(
                f"retrieval requires {DEFAULT_EMBEDDING_MODEL!r} with "
                f"dimension {DEFAULT_EMBEDDING_DIMENSION}"
            )
        self.model = model
        self.dimension = dimension
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(
            input=list(texts),
            model=self.model,
            dimensions=self.dimension,
        )
        rows = sorted(response.data, key=lambda row: row.index)
        vectors = [list(map(float, row.embedding)) for row in rows]
        if len(vectors) != len(texts) or any(len(vector) != self.dimension for vector in vectors):
            raise ValueError("embedding provider returned an unexpected dimension")
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed([text])
        return vectors[0]
