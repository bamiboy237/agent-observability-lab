"""Application service for proposing, reviewing, and consuming failure groups."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.failures.errors import (
    InvalidReviewDecision,
    InvalidReviewTransition,
    ProposalNotFound,
    UnconfirmedFailure,
)
from app.domain.failures.grouping import proposals_from_result
from app.domain.failures.repository import FailureReviewRepository
from app.domain.failures.schemas import (
    ConfirmedFailureGroup,
    FailureGroupProposal,
    FailureGroupResult,
    FailureGroupReview,
    FailureKind,
    ProposalStatus,
    ReviewDecision,
)


class FailureReviewService:
    """Own the human review lifecycle and its Phase 7 consumption boundary."""

    def __init__(self, repository: FailureReviewRepository) -> None:
        self._repository = repository

    async def propose_groups(
        self,
        result: FailureGroupResult,
        *,
        created_at: datetime | None = None,
    ) -> tuple[FailureGroupProposal, ...]:
        """Persist deterministic proposals, retaining a rejected equivalent."""
        saved: list[FailureGroupProposal] = []
        for proposal in proposals_from_result(result, created_at=created_at):
            saved.append(await self._repository.save_proposal(proposal))
        return tuple(saved)

    async def list_proposals(
        self,
        status: ProposalStatus | None = None,
    ) -> tuple[FailureGroupProposal, ...]:
        return await self._repository.list_proposals(status)

    async def get_proposal(self, proposal_id: UUID) -> FailureGroupProposal:
        proposal = await self._repository.get_proposal(proposal_id)
        if proposal is None:
            raise ProposalNotFound(proposal_id)
        return proposal

    async def review_proposal(
        self,
        *,
        proposal_id: UUID,
        decision: ReviewDecision,
        reviewer: str,
        reason: str,
        corrected_kind: FailureKind | None = None,
        reviewed_at: datetime | None = None,
    ) -> FailureGroupProposal:
        """Apply one review exactly once under a database row lock."""
        if not reviewer.strip():
            raise InvalidReviewDecision("reviewer identity is required")
        if not reason.strip():
            raise InvalidReviewDecision("review reason is required")
        if decision is ReviewDecision.CORRECT and corrected_kind is None:
            raise InvalidReviewDecision("correct decisions require a corrected failure kind")
        if decision is not ReviewDecision.CORRECT and corrected_kind is not None:
            raise InvalidReviewDecision("only correct decisions accept a corrected failure kind")
        await self._repository.lock_proposal(proposal_id)
        proposal = await self.get_proposal(proposal_id)
        if proposal.status is not ProposalStatus.PROPOSED:
            prior = await self._repository.get_review(proposal_id)
            if prior is not None and (
                prior.decision is decision
                and prior.reviewer == reviewer
                and prior.reason == reason
                and prior.corrected_kind is corrected_kind
            ):
                return proposal
            raise InvalidReviewTransition(proposal_id=proposal_id, state=proposal.status.value)
        now = reviewed_at or datetime.now(UTC)
        status = {
            ReviewDecision.CONFIRM: ProposalStatus.CONFIRMED,
            ReviewDecision.CORRECT: ProposalStatus.CORRECTED,
            ReviewDecision.REJECT: ProposalStatus.REJECTED,
        }[decision]
        review = FailureGroupReview(
            review_id=uuid4(),
            proposal_id=proposal.proposal_id,
            decision=decision,
            reviewer=reviewer,
            reason=reason,
            reviewed_at=now,
            corrected_kind=corrected_kind,
            source_evidence_ids=proposal.evidence_ids,
            evidence_event_ids=proposal.evidence_event_ids,
            algorithm_version=proposal.algorithm_version,
        )
        saved = await self._repository.save_review(review)
        if not saved:
            prior = await self._repository.get_review(proposal_id)
            if prior is not None:
                return await self.get_proposal(proposal_id)
            raise InvalidReviewTransition(proposal_id=proposal_id, state=proposal.status.value)
        updated = proposal.model_copy(
            update={
                "status": status,
                "reviewed_at": now,
                "reviewed_by": reviewer,
                "review_reason": reason,
                "corrected_kind": corrected_kind,
            }
        )
        await self._repository.update_proposal(updated)
        return updated

    async def require_confirmed(self, proposal_id: UUID) -> ConfirmedFailureGroup:
        """Return the only review shape that Phase 7 may consume."""
        proposal = await self.get_proposal(proposal_id)
        if proposal.status not in (ProposalStatus.CONFIRMED, ProposalStatus.CORRECTED):
            raise UnconfirmedFailure(proposal_id)
        review = await self._repository.get_review(proposal_id)
        if review is None:
            raise UnconfirmedFailure(proposal_id)
        return ConfirmedFailureGroup(
            proposal_id=proposal.proposal_id,
            group_id=proposal.group_id,
            failure_kind=proposal.corrected_kind or proposal.predicted_kind,
            evidence_ids=proposal.evidence_ids,
            evidence_event_ids=proposal.evidence_event_ids,
            review=review,
            dataset_id=proposal.dataset_id,
            dataset_version=proposal.dataset_version,
            algorithm_version=proposal.algorithm_version,
        )


__all__ = ["FailureReviewService"]
