"""This module defines the mounted HTTP route for one support-agent turn."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.pydantic_ai_agent import ModelConfig, PydanticAISupportAgent
from app.config import Settings, get_settings
from app.db import get_session
from app.domain.agent.errors import ModelNotConfigured
from app.domain.agent.schemas import SupportRequest, SupportResponse
from app.domain.retrieval.embeddings import OpenAIEmbeddingProvider
from app.domain.retrieval.fusion import FusedRetriever
from app.domain.retrieval.storage import KeywordRetriever, VectorRetriever
from app.domain.support.repository import SqlAlchemySupportRepository
from app.telemetry.config import build_tracer
from app.telemetry.recorder import TraceRecorder

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentTurnCommand(BaseModel):
    """This class stores the body of one agent turn request."""

    customer_id: UUID
    message: str = Field(min_length=1, max_length=2000)
    refund_confirmed: bool = False


def get_agent(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PydanticAISupportAgent:
    """This function builds the agent from settings.

    If the settings lack a complete model configuration, this function raises an error.
    """
    if not settings.model_configured:
        raise ModelNotConfigured()
    provider = settings.model_provider
    model_name = settings.model_name
    if provider is None or model_name is None:
        raise ModelNotConfigured()
    tracer = build_tracer(settings)
    recorder = TraceRecorder(tracer)
    model_config = ModelConfig(
        provider=provider,
        name=model_name,
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
    )
    policy_retriever = None
    embedding_key = settings.embedding_api_key or (
        settings.model_api_key if settings.model_provider == "openai" else None
    )
    if settings.retrieval_enabled and embedding_key is not None:
        embedding_provider = OpenAIEmbeddingProvider(
            api_key=embedding_key.get_secret_value(),
            base_url=settings.embedding_base_url,
        )
        policy_retriever = FusedRetriever(
            KeywordRetriever(session, corpus_version=settings.retrieval_corpus_version),
            VectorRetriever(
                session,
                embedding_provider,
                corpus_version=settings.retrieval_corpus_version,
            ),
            recorder=recorder,
            corpus_version=settings.retrieval_corpus_version,
        )
    return PydanticAISupportAgent(
        model_config=model_config,
        recorder=recorder,
        repository=SqlAlchemySupportRepository(session),
        policy_retriever=policy_retriever,
    )


@router.post("/turns", response_model=SupportResponse)
async def run_agent_turn(
    command: AgentTurnCommand,
    agent: Annotated[PydanticAISupportAgent, Depends(get_agent)],
) -> SupportResponse:
    return await agent.handle(
        SupportRequest(
            customer_id=command.customer_id,
            message=command.message,
            refund_confirmed=command.refund_confirmed,
        )
    )
