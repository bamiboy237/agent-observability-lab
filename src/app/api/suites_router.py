"""This module defines HTTP routes for the versioned regression suite library.

The routes are thin: they parse the request, delegate to the suite service,
and return stable typed results. List operations carry explicit limits.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from app.api.cases_router import MAX_LIST_LIMIT
from app.api.dependencies import get_suite_service
from app.domain.suite.schemas import CaseSuite, SuiteMemberRef, SuiteSaveResult, SuiteSummary
from app.domain.suite.service import SuiteService

router = APIRouter(prefix="/suites", tags=["suites"])


class SaveSuiteRequest(BaseModel):
    """This class stores the body of one suite save request."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    members: tuple[SuiteMemberRef, ...] = Field(min_length=1)


@router.post("", response_model=SuiteSaveResult, status_code=status.HTTP_201_CREATED)
async def save_suite(
    request: SaveSuiteRequest,
    service: Annotated[SuiteService, Depends(get_suite_service)],
) -> SuiteSaveResult:
    """This method saves one explicit member set as an immutable suite version."""
    return await service.save_suite(name=request.name, members=request.members)


@router.get("", response_model=list[SuiteSummary])
async def list_suites(
    service: Annotated[SuiteService, Depends(get_suite_service)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SuiteSummary]:
    """This method lists one summary per suite with explicit limits."""
    summaries = await service.list_suites()
    return list(summaries[offset : offset + limit])


@router.get("/{suite_id}/versions/{suite_version}", response_model=CaseSuite)
async def get_suite(
    suite_id: UUID,
    suite_version: int,
    service: Annotated[SuiteService, Depends(get_suite_service)],
) -> CaseSuite:
    """This method returns one exact immutable suite version."""
    return await service.get_suite(suite_id=suite_id, suite_version=suite_version)
