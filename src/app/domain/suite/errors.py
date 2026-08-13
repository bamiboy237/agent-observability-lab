"""This module defines typed failures for the regression suite library."""

from http import HTTPStatus
from uuid import UUID

from app.errors import DomainError


class SuiteError(DomainError):
    """This class represents an expected failure in the suite library."""


class SuiteNotFoundError(SuiteError):
    """This class represents a requested suite version that does not exist."""

    def __init__(self, *, suite_id: UUID, suite_version: int | None) -> None:
        suffix = f" version {suite_version}" if suite_version is not None else ""
        super().__init__(
            code="suite_not_found",
            message=f"No regression suite {suite_id}{suffix} exists",
            status_code=HTTPStatus.NOT_FOUND,
        )


class EmptySuiteError(SuiteError):
    """This class represents a suite that names no cases."""

    def __init__(self) -> None:
        super().__init__(
            code="empty_suite",
            message="A suite must name at least one exact case version",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class InvalidSuiteError(SuiteError):
    """This class represents a suite that violates the member contract."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            code="invalid_suite",
            message=f"The suite is invalid: {detail}",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class SuiteRunError(SuiteError):
    """This class represents a suite comparison that cannot run."""

    def __init__(self, *, detail: str, status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY) -> None:
        super().__init__(
            code="suite_run_rejected",
            message=f"The suite comparison cannot run: {detail}",
            status_code=status_code,
        )


class UnsupportedChangeError(SuiteError):
    """This class represents a validated dimension the reference runner cannot execute."""

    def __init__(self, *, change_type: str) -> None:
        super().__init__(
            code="unsupported_change_dimension",
            message=(
                f"The {change_type!r} change dimension is validated but not executable "
                "by the reference runner; use a model or prompt change"
            ),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
