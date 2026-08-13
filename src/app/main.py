from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.agent_router import router as agent_router
from app.api.cases_router import router as cases_router
from app.api.failures_router import router as failures_router
from app.api.health_router import router as health_router
from app.api.runs_router import comparisons_router, runs_router
from app.api.suites_router import router as suites_router
from app.api.support_router import router as support_router
from app.api.workflow_router import router as workflow_router
from app.config import Settings, get_settings
from app.errors import application_exception_handler
from app.logging import configure_logging, request_logger


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    app = FastAPI(title="Simulate")
    app.state.settings = settings
    app.dependency_overrides[get_settings] = lambda: settings

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
    app.include_router(support_router)
    app.include_router(workflow_router)
    app.include_router(agent_router)
    app.include_router(cases_router)
    app.include_router(suites_router)
    app.include_router(runs_router)
    app.include_router(comparisons_router)
    app.include_router(failures_router)
    return app
