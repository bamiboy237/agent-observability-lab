"""This module defines support errors with explicit types for the Phase 0 error handler."""

from http import HTTPStatus

from app.errors import DomainError


class SupportError(DomainError):
    """This class represents an expected failure from the support domain."""


class OrderNotFound(SupportError):
    """This class represents a request for an order that does not exist."""

    def __init__(self) -> None:
        super().__init__(
            code="order_not_found",
            message="The order was not found",
            status_code=HTTPStatus.NOT_FOUND,
        )


class Forbidden(SupportError):
    """This class represents an attempt to view an order without permission."""

    def __init__(self) -> None:
        super().__init__(
            code="forbidden",
            message="You are not allowed to view this order",
            status_code=HTTPStatus.FORBIDDEN,
        )


class InvalidTransition(SupportError):
    """This class represents an order status change that the domain does not allow."""

    def __init__(self) -> None:
        super().__init__(
            code="invalid_transition",
            message="The order cannot be refunded from its current status",
            status_code=HTTPStatus.CONFLICT,
        )


class PolicyNotFound(SupportError):
    """This class represents a request for a policy document that does not exist."""

    def __init__(self) -> None:
        super().__init__(
            code="policy_not_found",
            message="The policy document was not found",
            status_code=HTTPStatus.NOT_FOUND,
        )
