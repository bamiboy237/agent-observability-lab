"""This module defines typed failures for the simulation contract.

Adapters fail closed: unexpected tools, arguments, state, and missing
coverage raise these errors instead of returning a plausible response.
"""

from http import HTTPStatus

from app.errors import DomainError


class SimulationError(DomainError):
    """This class represents an expected failure during scenario simulation."""


class UnsupportedToolError(SimulationError):
    """This class represents a tool that one adapter does not offer."""

    def __init__(self, *, dependency: str, tool: str) -> None:
        super().__init__(
            code="unsupported_tool",
            message=(
                f"Dependency {dependency!r} does not offer tool {tool!r}; "
                "the adapter rejects unexpected access"
            ),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class UnsupportedArgumentsError(SimulationError):
    """This class represents arguments that no recorded response matches."""

    def __init__(self, *, dependency: str, tool: str, arguments: object) -> None:
        super().__init__(
            code="unsupported_arguments",
            message=(
                f"Dependency {dependency!r} has no recorded response for tool "
                f"{tool!r} with arguments {arguments!r}; the adapter never "
                "invents a plausible response"
            ),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class UnsupportedStateError(SimulationError):
    """This class represents state that an adapter cannot simulate."""

    def __init__(self, *, dependency: str, detail: str) -> None:
        super().__init__(
            code="unsupported_state",
            message=(f"Dependency {dependency!r} cannot simulate the requested state: {detail}"),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class MissingSimulationCoverageError(SimulationError):
    """This class represents a candidate that needs an unsupported dependency."""

    def __init__(self, *, tool: str) -> None:
        super().__init__(
            code="missing_simulation_coverage",
            message=(
                f"No simulated dependency covers tool {tool!r}; add a recorded "
                "or stateful adapter before running this candidate"
            ),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class InvalidSimulationFixture(SimulationError):
    """This class represents captured data that the sanitizer rejects."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            code="invalid_simulation_fixture",
            message=f"Captured fixture data failed sanitization: {detail}",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
