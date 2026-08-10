"""This module defines typed failures for the bundle compiler.

The compiler fails closed: missing evidence, missing coverage, rejected
reviews, forbidden data, and invalid fixtures raise these errors instead of
producing a bundle.
"""

from http import HTTPStatus

from app.errors import DomainError


class BundleError(DomainError):
    """This class represents an expected failure during bundle compilation."""


class MissingEvidenceError(BundleError):
    """This class represents a compilation without the required trace evidence."""

    def __init__(self, *, scenario_id: str, detail: str | None = None) -> None:
        super().__init__(
            code="missing_evidence",
            message=(
                f"Scenario {scenario_id!r} has no linked trace evidence; "
                "attach evidence before compiling a bundle"
                if detail is None
                else f"Scenario {scenario_id!r} cannot compile: {detail}"
            ),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class MissingCoverageError(BundleError):
    """This class represents a scenario whose dependencies lack simulation coverage."""

    def __init__(self, *, scenario_id: str, missing: tuple[str, ...]) -> None:
        super().__init__(
            code="missing_simulation_coverage",
            message=(
                f"Scenario {scenario_id!r} requires unsupported dependencies "
                f"{missing!r}; add recorded or stateful adapters before compiling"
            ),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class RejectedReviewError(BundleError):
    """This class represents a review that is not approved."""

    def __init__(self, *, scenario_id: str, state: str) -> None:
        super().__init__(
            code="review_not_approved",
            message=(
                f"Scenario {scenario_id!r} has review state {state!r}; "
                "only an approved review may produce an accepted bundle"
            ),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class ForbiddenDataError(BundleError):
    """This class represents data that the bundle scanner rejects."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            code="forbidden_data",
            message=f"Bundle scan rejected forbidden data: {detail}",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class InvalidBundleFixtureError(BundleError):
    """This class represents a fixture that fails allowlist sanitization."""

    def __init__(self, *, detail: str) -> None:
        super().__init__(
            code="invalid_bundle_fixture",
            message=f"Bundle fixture failed sanitization: {detail}",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
