from uuid import uuid4

from app.domain.retrieval.contracts import RetrievalHit
from app.domain.retrieval.fusion import reciprocal_rank_fusion


def hit(chunk_id: str, source: str, rank: int, score: float) -> RetrievalHit:
    identifier = uuid4()
    return RetrievalHit(
        chunk_id=identifier,
        document_id=identifier,
        document_version="policy-v1",
        text=chunk_id,
        score=score,
        source=source,  # type: ignore[arg-type]
        corpus_version="policy-v1",
        rank=rank,
    )


def test_rrf_deduplicates_and_keeps_contributing_ranks() -> None:
    shared = hit("shared", "keyword", 1, 0.9)
    vector_shared = shared.model_copy(update={"source": "vector", "rank": 2, "score": 0.8})
    separate = hit("separate", "vector", 1, 0.7)

    result = reciprocal_rank_fusion(((shared,), (separate, vector_shared)), limit=3, k=1)

    assert len(result) == 2
    assert result[0].chunk_id == shared.chunk_id
    assert result[0].source == "fused"
    assert result[0].contributing_ranks == {"keyword": 1, "vector": 2}
    assert result[0].rank == 1


def test_rrf_empty_and_invalid_inputs_are_safe() -> None:
    assert reciprocal_rank_fusion((), limit=5) == []
    assert reciprocal_rank_fusion(((hit("x", "keyword", 1, 1.0),),), limit=0) == []
    try:
        reciprocal_rank_fusion((), k=0)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive k must fail")
