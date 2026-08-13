from collections.abc import Sequence
from uuid import uuid4

from app.adapters.pydantic_ai_agent import AgentDeps, AnswerDraft, PydanticAISupportAgent
from app.domain.agent.instructions import (
    ACCEPTED_ANSWER_INSTRUCTIONS_VERSION,
    POLICY_SLUG,
)
from app.domain.agent.schemas import RouteIntent, RoutingDecision, SupportOutcome, SupportRequest
from app.domain.agent.service import SupportAgentService
from app.domain.retrieval.contracts import RetrievalHit
from app.domain.support.schemas import PolicyDocumentRead
from app.domain.support.service import SupportService
from app.telemetry.recorder import TraceRecorder
from tests.fakes.support_repository import InMemorySupportRepository


class FixedRetriever:
    def __init__(self, hits: Sequence[RetrievalHit]) -> None:
        self.hits = list(hits)

    async def search(self, query: str, limit: int = 5) -> list[RetrievalHit]:
        return self.hits[:limit]


def make_hit() -> RetrievalHit:
    identifier = uuid4()
    return RetrievalHit(
        chunk_id=identifier,
        document_id=identifier,
        document_version="2026-07-30",
        text="Delivered orders are eligible within 30 days.",
        score=0.99,
        source="fused",
        corpus_version="policy-v1",
        rank=1,
    )


def make_agent_for_assembly() -> PydanticAISupportAgent:
    agent = object.__new__(PydanticAISupportAgent)
    agent._answer_instructions_version = ACCEPTED_ANSWER_INSTRUCTIONS_VERSION
    agent._last_grounded = None
    return agent


async def make_service(hit: RetrievalHit) -> SupportAgentService:
    policy = PolicyDocumentRead(
        id=uuid4(),
        slug=POLICY_SLUG,
        version="2026-07-30",
        title="Refund policy",
        content="Delivered orders are eligible within 30 days.",
        content_hash="a" * 64,
    )
    service = SupportAgentService(
        SupportService(InMemorySupportRepository(policies=(policy,))),
        customer_id=uuid4(),
        recorder=TraceRecorder(None),
        policy_retriever=FixedRetriever((hit,)),  # type: ignore[arg-type]
    )
    service.set_request_message("How long do I have to request a refund?")
    await service.get_policy(POLICY_SLUG)
    service.record_tool_call("get_policy")
    return service


def deps_for(service: SupportAgentService) -> AgentDeps:
    return AgentDeps(
        customer_id=service.customer_id,
        service=service,
        recorder=TraceRecorder(None),
    )


async def test_policy_answer_exposes_only_supplied_fused_citations() -> None:
    hit = make_hit()
    service = await make_service(hit)
    agent = make_agent_for_assembly()
    routing = RoutingDecision(intent=RouteIntent.POLICY, confidence=1.0, policy_slug=POLICY_SLUG)

    response = agent._assemble(  # type: ignore[attr-defined]
        SupportRequest(customer_id=service.customer_id, message="policy"),
        routing,
        AnswerDraft(
            intent=RouteIntent.POLICY,
            message="You have 30 days.",
            citations=(str(hit.chunk_id),),
        ),
        deps_for(service),
    )

    assert response.outcome is SupportOutcome.COMPLETED
    assert response.context.citations[0].citation_id == str(hit.chunk_id)
    assert response.context.citations[0].text == hit.text


async def test_policy_answer_blocks_hallucinated_citation() -> None:
    hit = make_hit()
    service = await make_service(hit)
    agent = make_agent_for_assembly()
    routing = RoutingDecision(intent=RouteIntent.POLICY, confidence=1.0, policy_slug=POLICY_SLUG)

    response = agent._assemble(  # type: ignore[attr-defined]
        SupportRequest(customer_id=service.customer_id, message="policy"),
        routing,
        AnswerDraft(
            intent=RouteIntent.POLICY,
            message="This is not supported by the policy.",
            citations=(str(uuid4()),),
        ),
        deps_for(service),
    )

    assert response.outcome is SupportOutcome.BLOCKED
    assert response.context.citations == ()
