"""This module checks that the HTTP route for the agent returns a safe error if
the application lacks model settings.
"""

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.agent_router import router as agent_router
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import application_exception_handler
from app.main import create_app


def make_client(settings: Settings) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = "agent-router-test"
        try:
            return await call_next(request)
        except Exception as error:
            return await application_exception_handler(request, error)

    app.add_exception_handler(Exception, application_exception_handler)
    app.include_router(agent_router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: _fake_session()
    return TestClient(app)


async def _fake_session() -> AsyncGenerator[
    Annotated[AsyncSession | None, Depends(get_session)], None
]:
    yield None


def test_agent_turn_returns_503_when_model_not_configured() -> None:
    settings = Settings(
        database_url="postgresql://user:password@localhost:5432/app",
        _env_file=None,
    )
    response = make_client(settings).post(
        "/agent/turns",
        json={"customer_id": str(uuid4()), "message": "Where is my order?"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_configured"


def test_main_application_mounts_agent_router() -> None:
    settings = Settings(
        database_url="postgresql://user:password@localhost:5432/app",
        _env_file=None,
    )

    response = TestClient(create_app(settings)).post(
        "/agent/turns",
        json={"customer_id": str(uuid4()), "message": "Where is my order?"},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_not_configured"
