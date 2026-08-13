from uuid import uuid4

from app.domain.retrieval.contracts import RetrievalHit
from app.domain.retrieval.tracing import query_hash, record_retrieval_hits, record_retrieval_query
from app.telemetry.recorder import TraceRecorder


def test_retrieval_tracing_uses_query_hash_and_safe_hit_attributes() -> None:
    events: list[tuple[str, bool, dict[str, object]]] = []

    def listener(span: object, ended: bool) -> None:
        events.append((span.name, ended, dict(span.attributes)))  # type: ignore[attr-defined]

    recorder = TraceRecorder(None, span_listener=listener)
    identifier = uuid4()
    hit = RetrievalHit(
        chunk_id=identifier,
        document_id=identifier,
        document_version="policy-v1",
        text="secret customer message",
        score=0.9,
        source="keyword",
        corpus_version="policy-v1",
        rank=1,
    )
    record_retrieval_query(recorder, "secret customer message", "policy-v1")
    record_retrieval_hits(recorder, "keyword", [hit], "policy-v1")

    assert query_hash("secret customer message") in str(events)
    assert all("secret customer message" not in str(attributes) for _, _, attributes in events)
    assert any(name.endswith("keyword") for name, _, _ in events)
