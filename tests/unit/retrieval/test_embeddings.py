from typing import Any

import pytest

from app.domain.retrieval.embeddings import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
)


async def test_fake_embeddings_are_deterministic_and_ordered() -> None:
    provider = FakeEmbeddingProvider(dimension=8)
    first = await provider.embed(["refund policy", "order delivery"])
    second = await provider.embed(["refund policy", "order delivery"])

    assert first == second
    assert len(first) == 2
    assert all(len(vector) == 8 for vector in first)


class FakeEmbeddings:
    async def create(self, **kwargs: Any) -> Any:
        assert kwargs["model"] == DEFAULT_EMBEDDING_MODEL
        assert kwargs["dimensions"] == DEFAULT_EMBEDDING_DIMENSION
        return type(
            "Response",
            (),
            {
                "data": [
                    type(
                        "Row",
                        (),
                        {"index": 1, "embedding": [2.0] * DEFAULT_EMBEDDING_DIMENSION},
                    )(),
                    type(
                        "Row",
                        (),
                        {"index": 0, "embedding": [1.0] * DEFAULT_EMBEDDING_DIMENSION},
                    )(),
                ]
            },
        )()


class FakeClient:
    embeddings = FakeEmbeddings()


async def test_openai_adapter_sorts_response_by_input_order() -> None:
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        client=FakeClient(),  # type: ignore[arg-type]
        dimension=DEFAULT_EMBEDDING_DIMENSION,
    )
    vectors = await provider.embed(["first", "second"])
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 2.0


def test_openai_model_and_dimension_are_pinned_together() -> None:
    with pytest.raises(ValueError, match="text-embedding-3-small"):
        OpenAIEmbeddingProvider(api_key="test-key", model="other-model")
