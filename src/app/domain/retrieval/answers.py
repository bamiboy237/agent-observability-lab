"""Grounded policy answer assembly with strict citation validation."""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.retrieval.contracts import RetrievalHit
from app.domain.retrieval.errors import HallucinatedCitation


class PolicyCitation(BaseModel):
    """Exact evidence attached to one answer citation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    document_version: str = Field(min_length=1)


class CitedPolicyAnswer(BaseModel):
    """A policy answer whose citations resolve to retrieval hits."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str = Field(min_length=1, max_length=4000)
    citations: tuple[PolicyCitation, ...] = Field(min_length=1)


def build_cited_policy_answer(
    message: str,
    citation_ids: tuple[str, ...] | list[str],
    hits: list[RetrievalHit],
) -> CitedPolicyAnswer:
    """Resolve model citation IDs against the supplied hits.

    Unknown IDs fail closed.  The caller can then return a blocked response or
    escalate instead of presenting an unsupported policy claim.
    """
    by_id = {str(hit.chunk_id): hit for hit in hits}
    citations: list[PolicyCitation] = []
    for citation_id in citation_ids:
        hit = by_id.get(citation_id)
        if hit is None:
            raise HallucinatedCitation(citation_id)
        citations.append(
            PolicyCitation(
                citation_id=citation_id,
                text=hit.text,
                document_version=hit.document_version,
            )
        )
    if not citations:
        raise HallucinatedCitation("missing")
    return CitedPolicyAnswer(message=message, citations=tuple(citations))
