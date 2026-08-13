"""Checkpoint 6.5 tests for the human review lifecycle."""

import pytest

from app.domain.failures.dataset import load_failure_dataset
from app.domain.failures.errors import InvalidReviewTransition, UnconfirmedFailure
from app.domain.failures.features import extract_candidates
from app.domain.failures.grouping import group_candidates
from app.domain.failures.repository import InMemoryFailureReviewRepository
from app.domain.failures.schemas import FailureKind, ProposalStatus, ReviewDecision
from app.domain.failures.service import FailureReviewService


async def _service() -> tuple[FailureReviewService, object]:
    dataset = load_failure_dataset()
    result = group_candidates(
        extract_candidates(dataset.traces, dataset_version=1), min_samples=1
    )
    service = FailureReviewService(InMemoryFailureReviewRepository())
    proposals = await service.propose_groups(result)
    return service, proposals[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "corrected"),
    [
        (ReviewDecision.CONFIRM, None),
        (ReviewDecision.CORRECT, FailureKind.TOOL),
        (ReviewDecision.REJECT, None),
    ],
)
async def test_each_review_decision_is_persisted(decision, corrected) -> None:
    service, proposal = await _service()
    reviewed = await service.review_proposal(
        proposal_id=proposal.proposal_id,
        decision=decision,
        reviewer="reviewer-1",
        reason="checked source evidence",
        corrected_kind=corrected,
    )
    assert reviewed.status.value == {
        ReviewDecision.CONFIRM: "confirmed",
        ReviewDecision.CORRECT: "corrected",
        ReviewDecision.REJECT: "rejected",
    }[decision]
    if decision is ReviewDecision.REJECT:
        with pytest.raises(UnconfirmedFailure):
            await service.require_confirmed(proposal.proposal_id)
    else:
        confirmed = await service.require_confirmed(proposal.proposal_id)
        assert confirmed.review.decision is decision


@pytest.mark.asyncio
async def test_rejected_equivalent_does_not_reopen_and_review_is_idempotent() -> None:
    service, proposal = await _service()
    rejected = await service.review_proposal(
        proposal_id=proposal.proposal_id,
        decision=ReviewDecision.REJECT,
        reviewer="reviewer-1",
        reason="not a useful group",
    )
    repeated = await service.review_proposal(
        proposal_id=proposal.proposal_id,
        decision=ReviewDecision.REJECT,
        reviewer="reviewer-1",
        reason="not a useful group",
    )
    assert rejected.status is ProposalStatus.REJECTED
    assert repeated.proposal_id == rejected.proposal_id
    with pytest.raises(InvalidReviewTransition):
        await service.review_proposal(
            proposal_id=proposal.proposal_id,
            decision=ReviewDecision.CONFIRM,
            reviewer="reviewer-2",
            reason="changed mind",
        )
