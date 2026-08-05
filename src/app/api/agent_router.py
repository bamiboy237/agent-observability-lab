"""This module defines HTTP routes for the Phase 2 reference agent.

The application does not mount this router in ``app.main``.
The application needs one line in ``main.py`` to mount this router.
Tests exercise this router without the main application.
"""

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
    return PydanticAISupportAgent(
        model_config=model_config,
        recorder=recorder,
        repository=SqlAlchemySupportRepository(session),
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
