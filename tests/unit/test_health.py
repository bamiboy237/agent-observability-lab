from collections.abc import AsyncGenerator
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db import get_session
from app.main import create_app


class HealthySession:
    async def execute(self, statement: object) -> object:
        return object()


class UnavailableSession:
    async def execute(self, statement: object) -> object:
        raise SQLAlchemyError("database unavailable")


def test_healthz_stays_live_when_database_dependency_is_broken() -> None:
    app = create_app(make_test_settings())

    async def broken_session() -> AsyncGenerator[Any, None]:
        raise SQLAlchemyError("database unavailable")
        yield

    app.dependency_overrides[get_session] = broken_session

    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_healthy_database() -> None:
    app = create_app(make_test_settings())

    async def healthy_session() -> AsyncGenerator[HealthySession, None]:
        yield HealthySession()

    app.dependency_overrides[get_session] = healthy_session

    response = TestClient(app).get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_unavailable_database() -> None:
    app = create_app(make_test_settings())

    async def unavailable_session() -> AsyncGenerator[UnavailableSession, None]:
        yield UnavailableSession()

    app.dependency_overrides[get_session] = unavailable_session

    response = TestClient(app).get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def make_test_settings() -> Settings:
    return Settings(
        database_url="postgresql://user:password@localhost:5432/app",
        environment="test",
        _env_file=None,
    )
