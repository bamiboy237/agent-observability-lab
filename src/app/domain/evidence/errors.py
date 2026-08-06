"""This module defines typed errors for trace intake and source adapters.

The application maps provider failures into these safe typed errors.
Provider exceptions never escape the adapter boundary.
"""

from http import HTTPStatus

from app.errors import DomainError


class EvidenceError(DomainError):
    """This class represents an expected failure during trace intake."""


class InvalidEvidence(EvidenceError):
    """This class represents evidence that fails schema validation."""

    def __init__(self, *, message: str) -> None:
        super().__init__(
            code="invalid_evidence",
            message=message,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class UnsupportedTrace(EvidenceError):
    """This class represents a source record that cannot map into safe evidence."""

    def __init__(self, *, message: str) -> None:
        super().__init__(
            code="unsupported_trace",
            message=message,
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class TraceSourceError(EvidenceError):
    """This class represents a failure talking to an external trace source."""

    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(code=code, message=message, status_code=status_code)


class TraceAuthenticationError(TraceSourceError):
    """This class represents credentials that the trace source rejects."""

    def __init__(self) -> None:
        super().__init__(
            code="trace_source_authentication_failed",
            message="The trace source rejected the configured credentials",
            status_code=HTTPStatus.BAD_GATEWAY,
        )


class TraceNotFound(TraceSourceError):
    """This class represents a trace that does not exist or is not visible."""

    def __init__(self) -> None:
        super().__init__(
            code="trace_not_found",
            message="The requested trace was not found",
            status_code=HTTPStatus.NOT_FOUND,
        )


class TraceRateLimited(TraceSourceError):
    """This class represents a rate-limited trace source request."""

    def __init__(self) -> None:
        super().__init__(
            code="trace_source_rate_limited",
            message="The trace source rate-limited the request; retry later",
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
        )


class TraceSourceUnavailable(TraceSourceError):
    """This class represents an unreachable source or unusable source data."""

    def __init__(self) -> None:
        super().__init__(
            code="trace_source_unavailable",
            message="The trace source is unavailable",
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
