"""This module defines fixtures for unit tests of the Phase 2 agent."""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.telemetry.recorder import TraceRecorder


@pytest.fixture
def span_capture() -> tuple[TraceRecorder, InMemorySpanExporter]:
    """This fixture returns a trace recorder and an exporter that stores spans in
    memory for assertions.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    recorder = TraceRecorder(
        provider.get_tracer("agent-test"),
        forbidden_substrings=("test-secret-key",),
    )
    return recorder, exporter
