"""This module defines HTTP routes for customer support operations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.domain.support.repository import SqlAlchemySupportRepository
from app.domain.support.schemas import (
    CreateTicketCommand,
    OrderRead,
    RefundCommand,
    TicketRead,
)
from app.domain.support.service import SupportService

router = APIRouter(prefix="/support", tags=["support"])


def get_support_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SupportService:
    return SupportService(SqlAlchemySupportRepository(session))


@router.get("/orders/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: UUID,
    actor_id: Annotated[
        UUID,
        Query(
            description="Customer requesting access to the order",
            examples=["e693cb4c-98a7-5d3d-bd7a-1c0c554ab528"],
        ),
    ],
    service: Annotated[SupportService, Depends(get_support_service)],
) -> OrderRead:
    return await service.get_order(order_id, actor_id)


@router.post(
    "/tickets",
    response_model=TicketRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket(
    command: CreateTicketCommand,
    service: Annotated[SupportService, Depends(get_support_service)],
) -> TicketRead:
    return await service.create_ticket(command)


@router.post("/refunds", response_model=OrderRead)
async def request_refund(
    command: RefundCommand,
    service: Annotated[SupportService, Depends(get_support_service)],
) -> OrderRead:
    return await service.request_refund(command)
