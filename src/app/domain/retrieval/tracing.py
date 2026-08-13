"""Helpers for safe retrieval span attributes."""

from hashlib import sha256

from app.domain.retrieval.contracts import RetrievalHit
from app.telemetry.recorder import TraceRecorder


def query_hash(query: str) -> str:
    """Return a stable non-reversible identifier for a query."""
    return sha256(query.encode("utf-8")).hexdigest()


def record_retrieval_query(recorder: TraceRecorder, query: str, corpus_version: str) -> None:
    """Record query identity without storing raw user text."""
    recorder_span = recorder.span("support_agent.retrieval.query")
    with recorder_span as span:
        span.set_attribute("retrieval.query.hash", query_hash(query))
        span.set_attribute("retrieval.corpus.version", corpus_version)


def record_retrieval_hits(
    recorder: TraceRecorder,
    stage: str,
    hits: list[RetrievalHit],
    corpus_version: str,
) -> None:
    """Record safe hit IDs, ranks, and scores for a stage."""
    with recorder.span(f"support_agent.retrieval.{stage}") as span:
        span.set_attribute("retrieval.corpus.version", corpus_version)
        span.set_attribute("retrieval.hit.ids", ",".join(str(hit.chunk_id) for hit in hits))
        span.set_attribute("retrieval.hit.ranks", ",".join(str(hit.rank) for hit in hits))
        span.set_attribute(
            "retrieval.hit.scores", ",".join(f"{hit.score:.6f}" for hit in hits)
        )
