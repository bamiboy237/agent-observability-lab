"""Safe domain errors for failure proposal review."""

from http import HTTPStatus
from uuid import UUID

from app.errors import DomainError


class FailureReviewError(DomainError):
    """Base class for expected failure-review errors."""


class ProposalNotFound(FailureReviewError):
    def __init__(self, proposal_id: UUID) -> None:
        super().__init__(
            code="failure_group_not_found",
            message=f"No failure group proposal {proposal_id} exists",
            status_code=HTTPStatus.NOT_FOUND,
        )


class InvalidReviewTransition(FailureReviewError):
    def __init__(self, *, proposal_id: UUID, state: str) -> None:
        super().__init__(
            code="invalid_failure_review_transition",
            message=f"Failure group proposal {proposal_id} is already {state}",
            status_code=HTTPStatus.CONFLICT,
        )


class InvalidReviewDecision(FailureReviewError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            code="invalid_failure_review",
            message=detail,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class UnconfirmedFailure(FailureReviewError):
    def __init__(self, proposal_id: UUID) -> None:
        super().__init__(
            code="failure_group_review_required",
            message=f"Failure group proposal {proposal_id} is not confirmed",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
