from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import DomainError
from app.main import create_app


def test_domain_error_maps_to_safe_stable_response() -> None:
    app = create_app(make_test_settings())

    @app.get("/test-domain-error")
    async def raise_domain_error() -> None:
        raise DomainError(
            code="order_conflict",
            message="The order cannot be changed",
            status_code=409,
        )

    response = TestClient(app).get(
        "/test-domain-error",
        headers={"x-request-id": "domain-review"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "order_conflict",
            "message": "The order cannot be changed",
        },
        "request_id": "domain-review",
    }


def test_unexpected_error_does_not_leak_message_in_production() -> None:
    app = create_app(make_test_settings(environment="production"))

    @app.get("/test-unexpected-error")
    async def raise_unexpected_error() -> None:
        raise RuntimeError("database password is super-secret")

    response = TestClient(app).get(
        "/test-unexpected-error",
        headers={"x-request-id": "unexpected-review"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred",
        },
        "request_id": "unexpected-review",
    }
    assert "super-secret" not in response.text


def make_test_settings(environment: str = "test") -> Settings:
    return Settings(
        database_url="postgresql://user:password@localhost:5432/app",
        environment=environment,
        _env_file=None,
    )
