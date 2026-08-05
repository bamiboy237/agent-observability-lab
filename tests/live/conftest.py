"""This module defines fixtures for live Phase 2 checks that require credentials."""

import os
from collections.abc import Callable
from decimal import Decimal

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.adapters.pydantic_ai_agent import ModelConfig, PydanticAISupportAgent
from app.config import Settings
from app.domain.agent.instructions import POLICY_SLUG
from app.domain.support.schemas import OrderRead, OrderStatus, PolicyDocumentRead
from app.domain.support.seed import POLICY_CONTENT, seed_id
from app.telemetry.recorder import TraceRecorder
from tests.fakes.support_repository import InMemorySupportRepository


def build_live_settings() -> Settings | None:
    """If the environment lacks model settings, this function returns None.

    Otherwise, this function returns settings for live tests."""
    if not os.environ.get("MODEL_PROVIDER") or not os.environ.get("MODEL_NAME"):
        return None
    return Settings(
        database_url=os.environ.get("DATABASE_URL")
        or "postgresql://agent:agent@localhost:5432/app",
        model_provider=os.environ["MODEL_PROVIDER"],  # type: ignore[arg-type]
        model_name=os.environ["MODEL_NAME"],
        model_base_url=os.environ.get("MODEL_BASE_URL"),
        model_api_key=os.environ.get("MODEL_API_KEY"),
        otel_tracing_enabled=False,
        _env_file=None,
    )


def build_live_repository() -> InMemorySupportRepository:
    """This function returns an in-memory repository with records from the Phase 1 seed."""
    alex = seed_id("customer:alex-rivera")
    samira = seed_id("customer:samira-patel")
    orders = (
        OrderRead(
            id=seed_id("order:shipped"),
            customer_id=alex,
            status=OrderStatus.SHIPPED,
            total_amount=Decimal("135.00"),
        ),
        OrderRead(
            id=seed_id("order:delivered"),
            customer_id=samira,
            status=OrderStatus.DELIVERED,
            total_amount=Decimal("48.25"),
        ),
    )
    policy = PolicyDocumentRead(
        id=seed_id("policy:refund-and-delivery:2026-07-30"),
        slug=POLICY_SLUG,
        version="2026-07-30",
        title="Refund and Delivery Policy",
        content=POLICY_CONTENT,
        content_hash="",
    )
    return InMemorySupportRepository(orders=orders, policies=(policy,))


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    settings = build_live_settings()
    if settings is None:
        pytest.skip(
            "Live model checks need MODEL_PROVIDER and MODEL_NAME (plus MODEL_API_KEY "
            "for hosted endpoints); set them to run these checks."
        )
    return settings


@pytest.fixture(scope="session")
def live_model_config(live_settings: Settings) -> ModelConfig:
    provider = live_settings.model_provider
    model_name = live_settings.model_name
    assert provider is not None and model_name is not None
    return ModelConfig(
        provider=provider,
        name=model_name,
        base_url=live_settings.model_base_url,
        api_key=live_settings.model_api_key,
    )


@pytest.fixture
def span_capture() -> tuple[TraceRecorder, InMemorySpanExporter]:
    """This fixture returns a trace recorder and an exporter that stores spans in memory."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    recorder = TraceRecorder(
        provider.get_tracer("live-agent-test"),
        forbidden_substrings=(os.environ.get("MODEL_API_KEY") or "",),
    )
    return recorder, exporter


@pytest.fixture
def make_agent(
    live_model_config: ModelConfig,
) -> Callable[..., PydanticAISupportAgent]:
    """This fixture returns a factory.

    The factory creates live agents that use a trace recorder and a repository."""

    def build(
        recorder: TraceRecorder,
        repository: InMemorySupportRepository,
        **kwargs: object,
    ) -> PydanticAISupportAgent:
        return PydanticAISupportAgent(
            model_config=live_model_config,
            recorder=recorder,
            repository=repository,
            **kwargs,  # type: ignore[arg-type]
        )

    return build
