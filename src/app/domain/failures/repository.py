"""Persistence boundary for failure proposals and immutable reviews."""

from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.failures.models import FailureGroupProposalRecord, FailureGroupReviewRecord
from app.domain.failures.schemas import (
    FailureGroupProposal,
    FailureGroupReview,
    FailureKind,
    ProposalStatus,
    ReviewDecision,
)


class FailureReviewRepository(Protocol):
    async def list_proposals(
        self, status: ProposalStatus | None = None
    ) -> tuple[FailureGroupProposal, ...]: ...

    async def get_proposal(self, proposal_id: UUID) -> FailureGroupProposal | None: ...

    async def get_by_fingerprint(self, fingerprint: str) -> FailureGroupProposal | None: ...

    async def save_proposal(self, proposal: FailureGroupProposal) -> FailureGroupProposal: ...

    async def lock_proposal(self, proposal_id: UUID) -> None: ...

    async def update_proposal(self, proposal: FailureGroupProposal) -> None: ...

    async def save_review(self, review: FailureGroupReview) -> bool: ...

    async def get_review(self, proposal_id: UUID) -> FailureGroupReview | None: ...


class InMemoryFailureReviewRepository:
    """A concurrency-friendly fake that mirrors the public repository boundary."""

    def __init__(self) -> None:
        self.proposals: dict[UUID, FailureGroupProposal] = {}
        self.reviews: dict[UUID, FailureGroupReview] = {}

    async def list_proposals(
        self, status: ProposalStatus | None = None
    ) -> tuple[FailureGroupProposal, ...]:
        rows = tuple(self.proposals.values())
        if status is not None:
            rows = tuple(item for item in rows if item.status is status)
        return tuple(sorted(rows, key=lambda item: str(item.proposal_id)))

    async def get_proposal(self, proposal_id: UUID) -> FailureGroupProposal | None:
        return self.proposals.get(proposal_id)

    async def get_by_fingerprint(self, fingerprint: str) -> FailureGroupProposal | None:
        return next(
            (item for item in self.proposals.values() if item.proposal_fingerprint == fingerprint),
            None,
        )

    async def save_proposal(self, proposal: FailureGroupProposal) -> FailureGroupProposal:
        existing = await self.get_by_fingerprint(proposal.proposal_fingerprint)
        if existing is not None:
            return existing
        self.proposals[proposal.proposal_id] = proposal
        return proposal

    async def lock_proposal(self, proposal_id: UUID) -> None:
        return None

    async def update_proposal(self, proposal: FailureGroupProposal) -> None:
        self.proposals[proposal.proposal_id] = proposal

    async def save_review(self, review: FailureGroupReview) -> bool:
        if review.proposal_id in self.reviews:
            return False
        self.reviews[review.proposal_id] = review
        return True

    async def get_review(self, proposal_id: UUID) -> FailureGroupReview | None:
        return self.reviews.get(proposal_id)


class SqlAlchemyFailureReviewRepository:
    """PostgreSQL persistence with row locks for duplicate-safe review."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _proposal(row: FailureGroupProposalRecord) -> FailureGroupProposal:
        return FailureGroupProposal(
            proposal_id=row.proposal_id,
            group_id=row.group_id,
            proposal_fingerprint=row.proposal_fingerprint,
            dataset_id=row.dataset_id,
            dataset_version=row.dataset_version,
            algorithm_version=row.algorithm_version,
            predicted_kind=FailureKind(row.predicted_kind),
            candidate_ids=tuple(UUID(value) for value in row.candidate_ids_json),
            evidence_ids=tuple(UUID(value) for value in row.evidence_ids_json),
            evidence_event_ids={
                key: tuple(values) for key, values in row.evidence_event_ids_json.items()
            },
            shared_features={
                key: value
                for key, value in row.shared_features_json.items()
                if isinstance(value, (bool, int, float, str))
            },
            status=ProposalStatus(row.status),
            created_at=row.created_at,
            reviewed_at=row.reviewed_at,
            reviewed_by=row.reviewed_by,
            review_reason=row.review_reason,
            corrected_kind=(FailureKind(row.corrected_kind) if row.corrected_kind else None),
        )

    @staticmethod
    def _review(row: FailureGroupReviewRecord) -> FailureGroupReview:
        return FailureGroupReview(
            review_id=row.review_id,
            proposal_id=row.proposal_id,
            decision=ReviewDecision(row.decision),
            reviewer=row.reviewer,
            reason=row.reason,
            reviewed_at=row.reviewed_at,
            corrected_kind=(FailureKind(row.corrected_kind) if row.corrected_kind else None),
            source_evidence_ids=tuple(UUID(value) for value in row.source_evidence_ids_json),
            evidence_event_ids={
                key: tuple(values) for key, values in row.evidence_event_ids_json.items()
            },
            algorithm_version=row.algorithm_version,
        )

    async def list_proposals(
        self, status: ProposalStatus | None = None
    ) -> tuple[FailureGroupProposal, ...]:
        statement = select(FailureGroupProposalRecord).order_by(
            FailureGroupProposalRecord.created_at,
            FailureGroupProposalRecord.proposal_id,
        )
        if status is not None:
            statement = statement.where(FailureGroupProposalRecord.status == status.value)
        rows = (await self._session.scalars(statement)).all()
        return tuple(self._proposal(row) for row in rows)

    async def get_proposal(self, proposal_id: UUID) -> FailureGroupProposal | None:
        row = await self._session.get(FailureGroupProposalRecord, proposal_id)
        return self._proposal(row) if row is not None else None

    async def get_by_fingerprint(self, fingerprint: str) -> FailureGroupProposal | None:
        row = await self._session.scalar(
            select(FailureGroupProposalRecord).where(
                FailureGroupProposalRecord.proposal_fingerprint == fingerprint
            )
        )
        return self._proposal(row) if row is not None else None

    async def save_proposal(self, proposal: FailureGroupProposal) -> FailureGroupProposal:
        existing = await self.get_by_fingerprint(proposal.proposal_fingerprint)
        if existing is not None:
            return existing
        row = FailureGroupProposalRecord(
            proposal_id=proposal.proposal_id,
            group_id=proposal.group_id,
            proposal_fingerprint=proposal.proposal_fingerprint,
            dataset_id=proposal.dataset_id,
            dataset_version=proposal.dataset_version,
            algorithm_version=proposal.algorithm_version,
            predicted_kind=proposal.predicted_kind.value,
            candidate_ids_json=[str(value) for value in proposal.candidate_ids],
            evidence_ids_json=[str(value) for value in proposal.evidence_ids],
            evidence_event_ids_json={
                key: list(values) for key, values in proposal.evidence_event_ids.items()
            },
            shared_features_json=proposal.shared_features,
            status=proposal.status.value,
            created_at=proposal.created_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            existing = await self.get_by_fingerprint(proposal.proposal_fingerprint)
            if existing is None:
                raise
            return existing
        return proposal

    async def lock_proposal(self, proposal_id: UUID) -> None:
        await self._session.execute(
            select(FailureGroupProposalRecord)
            .where(FailureGroupProposalRecord.proposal_id == proposal_id)
            .with_for_update()
        )

    async def update_proposal(self, proposal: FailureGroupProposal) -> None:
        row = await self._session.get(FailureGroupProposalRecord, proposal.proposal_id)
        if row is None:
            return
        row.status = proposal.status.value
        row.reviewed_at = proposal.reviewed_at
        row.reviewed_by = proposal.reviewed_by
        row.review_reason = proposal.review_reason
        row.corrected_kind = proposal.corrected_kind.value if proposal.corrected_kind else None
        await self._session.flush()

    async def save_review(self, review: FailureGroupReview) -> bool:
        row = FailureGroupReviewRecord(
            review_id=review.review_id,
            proposal_id=review.proposal_id,
            decision=review.decision.value,
            reviewer=review.reviewer,
            reason=review.reason,
            reviewed_at=review.reviewed_at,
            corrected_kind=review.corrected_kind.value if review.corrected_kind else None,
            source_evidence_ids_json=[str(value) for value in review.source_evidence_ids],
            evidence_event_ids_json={
                key: list(values) for key, values in review.evidence_event_ids.items()
            },
            algorithm_version=review.algorithm_version,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            return False
        return True

    async def get_review(self, proposal_id: UUID) -> FailureGroupReview | None:
        row = await self._session.scalar(
            select(FailureGroupReviewRecord).where(
                FailureGroupReviewRecord.proposal_id == proposal_id
            )
        )
        return self._review(row) if row is not None else None
