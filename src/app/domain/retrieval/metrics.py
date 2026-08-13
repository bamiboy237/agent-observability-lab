"""Pure retrieval evaluation metrics."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.retrieval.contracts import RetrievalHit


@dataclass(frozen=True)
class RetrievalExample:
    """One versioned query and its hand-authored relevant chunk IDs."""

    case_id: str
    query: str
    expected_chunk_ids: tuple[str, ...]


def recall_at_k(
    results: Sequence[Sequence[RetrievalHit]],
    expected: Sequence[Sequence[str]],
    *,
    k: int,
) -> float:
    """Return the fraction of queries with at least one relevant top-k hit."""
    if len(results) != len(expected):
        raise ValueError("results and expected must have the same length")
    if not results:
        return 0.0
    if k < 1:
        raise ValueError("k must be positive")
    correct = sum(
        bool({str(hit.chunk_id) for hit in hits[:k]} & set(relevant))
        for hits, relevant in zip(results, expected, strict=True)
    )
    return correct / len(results)


def mean_reciprocal_rank(
    results: Sequence[Sequence[RetrievalHit]],
    expected: Sequence[Sequence[str]],
) -> float:
    """Return mean reciprocal rank for the first relevant result."""
    if len(results) != len(expected):
        raise ValueError("results and expected must have the same length")
    if not results:
        return 0.0
    total = 0.0
    for hits, relevant in zip(results, expected, strict=True):
        relevant_ids = set(relevant)
        for position, hit in enumerate(hits, start=1):
            if str(hit.chunk_id) in relevant_ids:
                total += 1.0 / position
                break
    return total / len(results)


def evaluate_results(
    examples: Sequence[RetrievalExample],
    results: Sequence[Sequence[RetrievalHit]],
    *,
    k: int = 5,
) -> dict[str, float | int]:
    """Calculate the stable metrics stored in evaluation artifacts."""
    expected = [example.expected_chunk_ids for example in examples]
    return {
        "query_count": len(examples),
        f"recall_at_{k}": recall_at_k(results, expected, k=k),
        "mrr": mean_reciprocal_rank(results, expected),
    }
