"""This module checks the configuration for trace export in checkpoint 2.5."""

from collections.abc import Generator
from typing import Any

import pytest

from app.config import Settings
from app.telemetry.config import (
    build_trace_provider,
    build_tracer,
    langsmith_export_config,
    reset_trace_cache,
)
from app.telemetry.recorder import TraceRecorder


@pytest.fixture(autouse=True)
def clear_trace_cache() -> Generator[None, None, None]:
    reset_trace_cache()
    yield
    reset_trace_cache()


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql://user:password@localhost:5432/app",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_export_disabled_without_settings() -> None:
    settings = make_settings()
    assert langsmith_export_config(settings) is None
    assert build_trace_provider(settings) is None
    assert build_tracer(settings) is None


def test_langsmith_export_disabled_when_tracing_off() -> None:
    settings = make_settings(langsmith_api_key="lsv2-test-key")
    assert langsmith_export_config(settings) is None


def test_langsmith_export_disabled_when_key_missing() -> None:
    settings = make_settings(langsmith_tracing=True)
    assert langsmith_export_config(settings) is None


def test_langsmith_export_enabled_when_complete() -> None:
    settings = make_settings(
        langsmith_tracing=True,
        langsmith_api_key="lsv2-test-key",
        langsmith_project="simulate",
    )

    config = langsmith_export_config(settings)

    assert config is not None
    assert config.project == "simulate"
    assert config.endpoint.startswith("https://")
    assert config.headers["x-api-key"] == "lsv2-test-key"
    assert config.headers["Langsmith-Project"] == "simulate"
    assert "lsv2-test-key" not in repr(config)

    provider = build_trace_provider(settings)
    assert provider is not None
    resource = provider.resource.attributes
    assert resource["service.name"] == "simulate"
    assert resource["agent.workflow.version"] == "2.0.0"


def test_local_console_export_enabled_when_requested() -> None:
    settings = make_settings(otel_tracing_enabled=True)
    provider = build_trace_provider(settings)
    assert provider is not None
    tracer = build_tracer(settings)
    assert tracer is not None
    assert TraceRecorder(tracer).enabled is True


def test_tracer_is_cached_per_configuration() -> None:
    settings = make_settings(otel_tracing_enabled=True)
    assert build_tracer(settings) is build_tracer(settings)

    other = make_settings(otel_tracing_enabled=True, environment="production")
    assert build_tracer(other) is not build_tracer(settings)
