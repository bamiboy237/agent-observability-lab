"""This module defines HTTP routes for the saved regression case library.

The routes are thin: they parse the request, delegate to the case service,
and return stable typed results. Business rules live in the domain service.
List operations carry explicit limits.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.api.dependencies import get_case_service
from app.domain.bundle.schemas import SimulationBundle
from app.domain.regression.schemas import (
    CaseSaveResult,
    CaseSourceType,
    CaseSummary,
    RegressionCase,
)
from app.domain.regression.service import RegressionCaseService

router = APIRouter(prefix="/cases", tags=["cases"])

MAX_LIST_LIMIT = 200


class SaveCaseRequest(BaseModel):
    """This class stores the body of one case save request."""

    bundle: SimulationBundle
    source_type: CaseSourceType


@router.post("", response_model=CaseSaveResult, status_code=status.HTTP_201_CREATED)
async def save_case(
    request: SaveCaseRequest,
    service: Annotated[RegressionCaseService, Depends(get_case_service)],
) -> CaseSaveResult:
    """This method saves one accepted bundle as an immutable case version."""
    return await service.save_case(
        bundle=request.bundle,
        source_type=request.source_type,
    )


@router.get("", response_model=list[CaseSummary])
async def list_cases(
    service: Annotated[RegressionCaseService, Depends(get_case_service)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CaseSummary]:
    """This method lists one summary per case with explicit limits."""
    summaries = await service.list_cases()
    return list(summaries[offset : offset + limit])


@router.get("/{case_id}/versions/{case_version}", response_model=RegressionCase)
async def get_case(
    case_id: UUID,
    case_version: int,
    service: Annotated[RegressionCaseService, Depends(get_case_service)],
) -> RegressionCase:
    """This method returns one exact immutable case version."""
    return await service.get_case(case_id=case_id, case_version=case_version)
