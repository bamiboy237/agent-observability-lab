"""This module defines routes that check the application's health."""

import asyncio

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter()
READINESS_TIMEOUT_SECONDS = 2.0


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


async def readiness_check(session: AsyncSession) -> bool:
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
        return True
    except (TimeoutError, SQLAlchemyError):
        return False


@router.get("/readyz", status_code=status.HTTP_200_OK)
async def readiness(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    if not await readiness_check(session):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable"},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok"},
    )
