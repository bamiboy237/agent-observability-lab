"""This module defines typed failures for the regression case library.

The service fails closed: a bundle without an approved review, a bundle
whose stored content hash does not match its content, and a missing case
version raise these errors instead of storing or returning bad data.
"""

from http import HTTPStatus
from uuid import UUID

from app.errors import DomainError


class RegressionCaseError(DomainError):
    """This class represents an expected failure in the case library."""


class ReviewRequiredError(RegressionCaseError):
    """This class represents a bundle that is not approved by a reviewer."""

    def __init__(self, *, scenario_id: str, state: str) -> None:
        super().__init__(
            code="case_review_required",
            message=(
                f"Scenario {scenario_id!r} has review state {state!r}; "
                "only an approved review may save an accepted regression case"
            ),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class InvalidCaseBundleError(RegressionCaseError):
    """This class represents a bundle whose content hash does not match its content."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            code="invalid_case_bundle",
            message=f"The bundle cannot enter the case library: {detail}",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class CaseNotFoundError(RegressionCaseError):
    """This class represents a requested case version that does not exist."""

    def __init__(self, *, case_id: UUID, case_version: int | None) -> None:
        suffix = f" version {case_version}" if case_version is not None else ""
        super().__init__(
            code="case_not_found",
            message=f"No regression case {case_id}{suffix} exists",
            status_code=HTTPStatus.NOT_FOUND,
        )
