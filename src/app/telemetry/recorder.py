"""This module records spans for the reference agent.

The agent and its tools emit spans only through ``TraceRecorder``.
If the application disables tracing, the recorder has no OpenTelemetry tracer.
Each recorder method then returns without telemetry work.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import INVALID_TRACE_ID, Span, SpanContext, Tracer

from app.telemetry.allowlist import sanitize_attributes


class TraceSpan:
    """This class writes attributes after sanitization for one span."""

    def set_attribute(self, name: str, value: object) -> None:
        """This method records one allowlisted attribute and drops every other attribute."""

    def set_error(self, reason_code: str) -> None:
        """This method marks the span as failed with a stable, safe reason code."""

    def span_context(self) -> SpanContext | None:
        """This method returns the underlying span context.

        If the application disables tracing, this method returns ``None``.
        """

    def end(self) -> None:
        """This method finishes the span before the context manager exits."""


class NullSpan(TraceSpan):
    """This class represents a span that performs no telemetry work."""

    def set_attribute(self, name: str, value: object) -> None:
        return None

    def set_error(self, reason_code: str) -> None:
        return None

    def span_context(self) -> SpanContext | None:
        return None

    def end(self) -> None:
        return None


class _OtelSpanWrapper(TraceSpan):
    def __init__(
        self,
        span: Span,
        forbidden_substrings: tuple[str, ...],
    ) -> None:
        self._span = span
        self._forbidden = forbidden_substrings

    def set_attribute(self, name: str, value: object) -> None:
        sanitized = sanitize_attributes({name: value}, self._forbidden)
        for key, clean_value in sanitized.items():
            self._span.set_attribute(key, clean_value)
            # LangSmith indexes only attributes with its own prefixes. Mirror
            # the allowlisted value so imported runs keep the same evidence.
            self._span.set_attribute(f"langsmith.metadata.{key}", clean_value)

    def set_error(self, reason_code: str) -> None:
        from opentelemetry.trace import Status, StatusCode

        self._span.set_status(Status(StatusCode.ERROR, reason_code))

    def span_context(self) -> SpanContext | None:
        return self._span.get_span_context()

    def end(self) -> None:
        self._span.end()


_NULL_SPAN = NullSpan()


class TraceRecorder:
    """This class records sanitized spans.

    If the application disables tracing, this class skips telemetry work.
    """

    def __init__(
        self,
        tracer: Tracer | None,
        forbidden_substrings: tuple[str, ...] = (),
    ) -> None:
        self._tracer = tracer
        self._forbidden = tuple(forbidden_substrings)

    @property
    def enabled(self) -> bool:
        return self._tracer is not None

    @contextmanager
    def span(
        self,
        name: str,
        attributes: Mapping[str, object] | None = None,
    ) -> Iterator[TraceSpan]:
        """This method starts a sanitized child span for the current context."""
        if self._tracer is None:
            yield _NULL_SPAN
            return
        # record_exception=False: exceptions that escape a span would otherwise
        # be exported as exception events with full stack traces, bypassing the
        # allowlist. Status is set explicitly with stable reason codes instead.
        with self._tracer.start_as_current_span(
            name,
            record_exception=False,
            set_status_on_exception=False,
        ) as otel_span:
            wrapper = _OtelSpanWrapper(otel_span, self._forbidden)
            if attributes:
                for key, value in sanitize_attributes(attributes, self._forbidden).items():
                    otel_span.set_attribute(key, value)
            yield wrapper

    def current_trace_id(self) -> str | None:
        """This method returns the hexadecimal trace ID of the current span.

        If no current span exists, this method returns ``None``.
        """
        if self._tracer is None:
            return None
        span_context = trace.get_current_span().get_span_context()
        if span_context.trace_id in (0, INVALID_TRACE_ID):
            return None
        return f"{span_context.trace_id:032x}"
