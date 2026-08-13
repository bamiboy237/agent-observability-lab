"""HTTP operations for explainable failure group review."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.dependencies import get_failure_review_service
from app.domain.failures.schemas import (
    FailureGroupProposal,
    FailureKind,
    ProposalStatus,
    ReviewDecision,
)
from app.domain.failures.service import FailureReviewService

router = APIRouter(prefix="/failure-groups", tags=["failures"])


class ReviewFailureGroupRequest(BaseModel):
    """The explicit human decision for one proposed group."""

    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)
    corrected_kind: FailureKind | None = None


@router.get("", response_model=list[FailureGroupProposal])
async def list_failure_groups(
    service: Annotated[FailureReviewService, Depends(get_failure_review_service)],
    status: Annotated[ProposalStatus | None, Query()] = None,
) -> list[FailureGroupProposal]:
    return list(await service.list_proposals(status))


@router.get("/{proposal_id}", response_model=FailureGroupProposal)
async def get_failure_group(
    proposal_id: UUID,
    service: Annotated[FailureReviewService, Depends(get_failure_review_service)],
) -> FailureGroupProposal:
    return await service.get_proposal(proposal_id)


@router.post("/{proposal_id}/review", response_model=FailureGroupProposal)
async def review_failure_group(
    proposal_id: UUID,
    request: ReviewFailureGroupRequest,
    service: Annotated[FailureReviewService, Depends(get_failure_review_service)],
) -> FailureGroupProposal:
    return await service.review_proposal(
        proposal_id=proposal_id,
        decision=request.decision,
        reviewer=request.reviewer,
        reason=request.reason,
        corrected_kind=request.corrected_kind,
    )
