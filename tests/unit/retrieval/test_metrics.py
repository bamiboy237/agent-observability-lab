from uuid import uuid4

from app.domain.retrieval.contracts import RetrievalHit
from app.domain.retrieval.metrics import (
    RetrievalExample,
    evaluate_results,
    mean_reciprocal_rank,
    recall_at_k,
)


def result(rank: int, chunk_id: str) -> RetrievalHit:
    identifier = uuid4()
    return RetrievalHit(
        chunk_id=identifier,
        document_id=identifier,
        document_version="policy-v1",
        text=chunk_id,
        score=1.0 / rank,
        source="keyword",
        corpus_version="policy-v1",
        rank=rank,
    )


def test_recall_and_mrr_are_pure_and_rank_sensitive() -> None:
    first = result(1, "first")
    second = result(2, "second")
    results = [[first, second], [second]]

    assert recall_at_k(results, [[str(first.chunk_id)], [str(first.chunk_id)]], k=1) == 0.5
    assert mean_reciprocal_rank(results, [[str(first.chunk_id)], [str(first.chunk_id)]]) == 0.5
    examples = [
        RetrievalExample("a", "one", (str(first.chunk_id),)),
        RetrievalExample("b", "two", (str(second.chunk_id),)),
    ]
    assert evaluate_results(examples, results)["query_count"] == 2
