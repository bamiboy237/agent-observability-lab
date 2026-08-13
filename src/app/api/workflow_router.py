"""Thin HTTP routes for starting and safely resuming support workflows."""

from collections.abc import AsyncIterator
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Depends
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.domain.support.repository import SqlAlchemySupportRepository
from app.domain.workflow.models import WorkflowRequest, WorkflowResponse
from app.domain.workflow.service import WorkflowService, default_dependencies
from app.telemetry.config import build_tracer
from app.telemetry.recorder import TraceRecorder

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _psycopg_url(settings: Settings) -> str:
    """Convert the application asyncpg URL to the psycopg checkpoint URL."""
    parsed = urlsplit(str(settings.migration_database_url))
    scheme = "postgresql" if parsed.scheme == "postgresql+asyncpg" else parsed.scheme
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    ssl = query.pop("ssl", None)
    query.pop("channel_binding", None)
    if ssl is not None:
        query["sslmode"] = ssl
    return urlunsplit(parsed._replace(scheme=scheme, query=urlencode(query)))


async def get_workflow_service(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[WorkflowService]:
    """Build the workflow service from the normal support persistence boundary."""
    recorder = TraceRecorder(build_tracer(settings))
    dependencies = default_dependencies(SqlAlchemySupportRepository(session), recorder)
    # The saver owns an async connection and is request-scoped here. Checkpoint
    # rows persist in PostgreSQL, so a later request may construct a new service
    # instance and resume the same workflow. ``setup`` is idempotent and is
    # intentionally explicit; deployments can also run it during startup.
    async with AsyncPostgresSaver.from_conn_string(_psycopg_url(settings)) as checkpointer:
        await checkpointer.setup()
        yield WorkflowService(dependencies, checkpointer=checkpointer)


@router.post("", response_model=WorkflowResponse)
async def start_workflow(
    request: WorkflowRequest,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowResponse:
    return await service.start(request)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def inspect_workflow(
    workflow_id: str,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowResponse:
    return await service.inspect(workflow_id)


class ResumeCommand(BaseModel):
    """The actor and request binding required to resume a paused workflow."""

    actor_id: UUID
    request_id: str = Field(min_length=1, max_length=200)


@router.post("/{workflow_id}/confirm", response_model=WorkflowResponse)
async def confirm_workflow(
    workflow_id: str,
    command: ResumeCommand,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowResponse:
    return await service.confirm(workflow_id, command.actor_id, command.request_id)


@router.post("/{workflow_id}/reject", response_model=WorkflowResponse)
async def reject_workflow(
    workflow_id: str,
    command: ResumeCommand,
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowResponse:
    return await service.reject(workflow_id, command.actor_id, command.request_id)
