"""Safe application error responses."""

from fastapi import Request, status
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """An expected application failure safe to return to a client."""

    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def application_exception_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    """Map expected and unexpected failures to stable, safe responses."""
    if isinstance(error, DomainError):
        code = error.code
        message = error.message
        status_code = error.status_code
    else:
        code = "internal_error"
        message = "An unexpected error occurred"
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "request_id": request.state.request_id,
        },
    )
