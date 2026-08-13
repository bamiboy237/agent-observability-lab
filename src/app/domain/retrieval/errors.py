"""Typed failures from the retrieval boundary."""

from http import HTTPStatus

from app.errors import DomainError


class RetrievalError(DomainError):
    """Base class for safe retrieval failures."""


class EmbeddingDimensionMismatch(RetrievalError):
    """The configured provider returned vectors with the wrong dimension."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            code="embedding_dimension_mismatch",
            message=f"The embedding dimension was {actual}; expected {expected}",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


class EmbeddingProviderUnavailable(RetrievalError):
    """The embedding provider failed without exposing provider details."""

    def __init__(self) -> None:
        super().__init__(
            code="embedding_provider_unavailable",
            message="The embedding provider is unavailable",
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )


class HallucinatedCitation(RetrievalError):
    """The answer cited a chunk that was not supplied by retrieval."""

    def __init__(self, citation_id: str) -> None:
        super().__init__(
            code="hallucinated_citation",
            message=f"The citation {citation_id!r} was not returned by retrieval",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
