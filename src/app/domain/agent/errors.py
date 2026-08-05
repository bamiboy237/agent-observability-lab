"""This module defines typed errors for deterministic guards in the reference agent."""

from http import HTTPStatus

from app.errors import DomainError


class AgentError(DomainError):
    """This class represents an expected failure from the agent."""


class ModelNotConfigured(AgentError):
    """This class represents a request for an agent without a configured hosted model."""

    def __init__(self) -> None:
        super().__init__(
            code="model_not_configured",
            message="The support agent is not configured",
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )


class RefundNotConfirmed(AgentError):
    """This class represents a refund request without explicit matching confirmation."""

    def __init__(self) -> None:
        super().__init__(
            code="refund_not_confirmed",
            message="The refund was not explicitly confirmed",
            status_code=HTTPStatus.CONFLICT,
        )
