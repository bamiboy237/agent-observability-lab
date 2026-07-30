"""Health router to check the health of the application."""
from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter()


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


async def readiness_check(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


@router.get("/readyz", status_code=status.HTTP_200_OK)
async def readiness(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    if not await readiness_check(session):
        return {"status": "not ready"}
    return {"status": "ok"}
