import json
import logging
from collections.abc import AsyncGenerator
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import get_session
from app.logging import JsonFormatter, request_logger
from app.main import create_app


class HealthySession:
    async def execute(self, statement: object) -> object:
        return object()


def test_supplied_request_id_is_returned_and_structured_in_logs() -> None:
    app = create_app(make_test_settings())

    async def healthy_session() -> AsyncGenerator[HealthySession, None]:
        yield HealthySession()

    app.dependency_overrides[get_session] = healthy_session
    with patch.object(request_logger, "info") as log_request:
        response = TestClient(app).get(
            "/readyz",
            headers={"x-request-id": "review-0.4"},
        )

    log_request.assert_called_once()
    extra = log_request.call_args.kwargs["extra"]
    record = logging.makeLogRecord(
        {
            "name": request_logger.name,
            "levelname": "INFO",
            "msg": "request completed",
            **extra,
        }
    )
    payload = json.loads(JsonFormatter().format(record))
    assert response.headers["x-request-id"] == "review-0.4"
    assert payload["request_id"] == "review-0.4"
    assert payload["status_code"] == 200


def test_missing_request_id_is_generated() -> None:
    response = TestClient(create_app(make_test_settings())).get("/healthz")

    assert response.headers["x-request-id"]


def make_test_settings() -> Settings:
    return Settings(
        database_url="postgresql://user:password@localhost:5432/app",
        environment="test",
        _env_file=None,
    )
