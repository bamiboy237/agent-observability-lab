from uuid import uuid4

import pytest

from app.domain.retrieval.answers import build_cited_policy_answer
from app.domain.retrieval.contracts import RetrievalHit
from app.domain.retrieval.errors import HallucinatedCitation


def make_hit() -> RetrievalHit:
    identifier = uuid4()
    return RetrievalHit(
        chunk_id=identifier,
        document_id=identifier,
        document_version="2026-07-30",
        text="Refunds are available within 30 days.",
        score=1.0,
        source="fused",
        corpus_version="policy-v1",
        rank=1,
    )


def test_cited_answer_resolves_exact_retrieval_text() -> None:
    hit = make_hit()
    answer = build_cited_policy_answer("You have 30 days.", [str(hit.chunk_id)], [hit])

    assert answer.citations[0].text == hit.text
    assert answer.citations[0].document_version == "2026-07-30"


def test_cited_answer_rejects_unknown_citation_id() -> None:
    with pytest.raises(HallucinatedCitation):
        build_cited_policy_answer("Unsupported", ["not-a-hit"], [make_hit()])
