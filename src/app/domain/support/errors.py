"""Typed support-domain errors mapped by the Phase 0 error handler."""

from http import HTTPStatus

from app.errors import DomainError


class SupportError(DomainError):
    """Base class for expected support-domain failures."""


class OrderNotFound(SupportError):
    """Raised when the requested order does not exist."""

    def __init__(self) -> None:
        super().__init__(
            code="order_not_found",
            message="The order was not found",
            status_code=HTTPStatus.NOT_FOUND,
        )


class Forbidden(SupportError):
    """Raised when an actor may not view an existing order."""

    def __init__(self) -> None:
        super().__init__(
            code="forbidden",
            message="You are not allowed to view this order",
            status_code=HTTPStatus.FORBIDDEN,
        )


class InvalidTransition(SupportError):
    """Raised when an order cannot move to the requested status."""

    def __init__(self) -> None:
        super().__init__(
            code="invalid_transition",
            message="The order cannot be refunded from its current status",
            status_code=HTTPStatus.CONFLICT,
        )
