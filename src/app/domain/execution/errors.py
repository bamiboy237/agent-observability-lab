"""This module defines typed failures for background case executions."""

from http import HTTPStatus
from uuid import UUID

from app.errors import DomainError


class ExecutionError(DomainError):
    """This class represents an expected failure in case execution."""


class ExecutionNotFoundError(ExecutionError):
    """This class represents an execution id that does not exist."""

    def __init__(self, *, execution_id: UUID) -> None:
        super().__init__(
            code="execution_not_found",
            message=f"No execution {execution_id} exists",
            status_code=HTTPStatus.NOT_FOUND,
        )


class SandboxUnavailableError(ExecutionError):
    """This class represents an environment that cannot isolate a simulation run."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            code="sandbox_unavailable",
            message=f"Simulation runs need an isolated test environment: {detail}",
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )
