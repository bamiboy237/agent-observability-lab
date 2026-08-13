"""Deterministic reciprocal-rank fusion."""

from collections.abc import Sequence
from hashlib import sha256

from app.domain.retrieval.contracts import RetrievalHit, Retriever
from app.telemetry.recorder import TraceRecorder

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[RetrievalHit]],
    *,
    limit: int = 5,
    k: int = DEFAULT_RRF_K,
) -> list[RetrievalHit]:
    """Fuse ranked lists while retaining every contributing rank.

    Ties resolve by chunk ID, then document version, so repeated runs produce
    the same output independently of database row order.
    """
    if limit < 1:
        return []
    if k < 1:
        raise ValueError("k must be positive")
    merged: dict[object, RetrievalHit] = {}
    scores: dict[object, float] = {}
    ranks: dict[object, dict[str, int]] = {}
    source_scores: dict[object, dict[str, float]] = {}
    for hits in ranked_lists:
        for position, hit in enumerate(hits, start=1):
            key = hit.chunk_id
            source = hit.source
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position)
            ranks.setdefault(key, {})[source] = position
            source_scores.setdefault(key, {})[source] = hit.score
            merged.setdefault(key, hit)
    ordered = sorted(
        merged.values(),
        key=lambda hit: (-scores[hit.chunk_id], str(hit.chunk_id)),
    )
    result: list[RetrievalHit] = []
    for position, hit in enumerate(ordered[:limit], start=1):
        result.append(
            hit.model_copy(
                update={
                    "source": "fused",
                    "score": scores[hit.chunk_id],
                    "rank": position,
                    "contributing_ranks": ranks[hit.chunk_id],
                    "contributing_scores": source_scores[hit.chunk_id],
                }
            )
        )
    return result


class FusedRetriever:
    """Run keyword and vector retrieval, then fuse them with deterministic RRF."""

    def __init__(
        self,
        keyword: Retriever,
        vector: Retriever,
        *,
        recorder: TraceRecorder | None = None,
        corpus_version: str = "policy-v1",
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        self.keyword = keyword
        self.vector = vector
        self._recorder = recorder
        self.corpus_version = corpus_version
        self.rrf_k = rrf_k

    async def _search_stage(
        self,
        retriever: Retriever,
        stage: str,
        query: str,
        limit: int,
    ) -> list[RetrievalHit]:
        recorder = self._recorder
        if recorder is None:
            return await retriever.search(query, limit)
        with recorder.span(f"support_agent.retrieval.{stage}") as span:
            hits = await retriever.search(query, limit)
            _record_hits(span, hits, self.corpus_version)
            return hits

    async def search(self, query: str, limit: int = 5) -> list[RetrievalHit]:
        if limit < 1 or not query.strip():
            return []
        if self._recorder is not None:
            with self._recorder.span("support_agent.retrieval.query") as span:
                span.set_attribute(
                    "retrieval.query.hash",
                    sha256(query.encode("utf-8")).hexdigest(),
                )
                span.set_attribute("retrieval.corpus.version", self.corpus_version)
        keyword = await self._search_stage(self.keyword, "keyword", query, limit)
        vector = await self._search_stage(self.vector, "vector", query, limit)
        result = reciprocal_rank_fusion((keyword, vector), limit=limit, k=self.rrf_k)
        if self._recorder is not None:
            with self._recorder.span("support_agent.retrieval.fusion") as span:
                span.set_attribute("retrieval.fusion.k", self.rrf_k)
                _record_hits(span, result, self.corpus_version)
        return result


def _record_hits(span: object, hits: Sequence[RetrievalHit], corpus_version: str) -> None:
    """Record safe, bounded retrieval evidence without raw query text."""
    span.set_attribute("retrieval.corpus.version", corpus_version)  # type: ignore[attr-defined]
    span.set_attribute(  # type: ignore[attr-defined]
        "retrieval.hit.ids", ",".join(str(hit.chunk_id) for hit in hits)
    )
    span.set_attribute(  # type: ignore[attr-defined]
        "retrieval.hit.ranks", ",".join(str(hit.rank) for hit in hits)
    )
    span.set_attribute(  # type: ignore[attr-defined]
        "retrieval.hit.scores", ",".join(f"{hit.score:.6f}" for hit in hits)
    )
