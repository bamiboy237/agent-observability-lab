from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.health_router import router as health_router
from app.config import Settings, get_settings
from app.errors import application_exception_handler
from app.logging import configure_logging, request_logger


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    app = FastAPI(title="Agent Observability Lab")
    app.state.settings = settings

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid4().hex
        request.state.request_id = request_id
        started_at = perf_counter()

        try:
            response = await call_next(request)
        except Exception as error:
            response = await application_exception_handler(request, error)

        response.headers["x-request-id"] = request_id
        request_logger.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return response

    app.add_exception_handler(Exception, application_exception_handler)
    app.include_router(health_router)
    return app
