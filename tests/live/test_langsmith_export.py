"""This module tests live span export through LangSmith and OpenTelemetry.

If the environment lacks LangSmith tracing, an API key, or a hosted model,
the test runner skips the test.
The test runs one real agent turn with local span capture.
The test sends finished spans to LangSmith through the OTLP exporter.
The test checks for a successful export response.
"""

import os

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.adapters.pydantic_ai_agent import ModelConfig, PydanticAISupportAgent
from app.domain.agent.schemas import SupportRequest
from app.domain.support.seed import seed_id
from app.telemetry.config import langsmith_export_config
from app.telemetry.recorder import TraceRecorder
from tests.live.conftest import build_live_repository, build_live_settings

pytestmark = pytest.mark.skipif(
    not (os.environ.get("LANGSMITH_TRACING") == "true" and os.environ.get("LANGSMITH_API_KEY")),
    reason="LangSmith export needs LANGSMITH_TRACING=true and LANGSMITH_API_KEY",
)


async def test_langsmith_otlp_export_accepts_sanitized_trace(
    live_model_config: ModelConfig,
) -> None:
    live_settings = build_live_settings()
    assert live_settings is not None
    export_config = langsmith_export_config(live_settings)
    assert export_config is not None, "export config must be complete for this test"

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    recorder = TraceRecorder(
        provider.get_tracer("langsmith-live-test"),
        forbidden_substrings=(os.environ.get("MODEL_API_KEY") or "",),
    )
    agent = PydanticAISupportAgent(
        model_config=live_model_config,
        recorder=recorder,
        repository=build_live_repository(),
    )
    request = SupportRequest(
        customer_id=seed_id("customer:alex-rivera"),
        message=f"What is the status of my order {seed_id('order:shipped')}?",
    )

    response = await agent.handle(request)

    spans = exporter.get_finished_spans()
    assert spans, "the agent turn must produce spans locally"
    for span in spans:
        serialized = str(span.attributes)
        assert request.message not in serialized
        assert "alex.rivera@example.test" not in serialized

    otlp_exporter = export_config.otlp_exporter()
    result = otlp_exporter.export(spans)
    from opentelemetry.sdk.trace.export import SpanExportResult

    assert result is SpanExportResult.SUCCESS
    print(
        f"LangSmith export ok: project={export_config.project} "
        f"trace_id={response.trace_id} spans={len(spans)}"
    )
