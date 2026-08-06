"""This module maps one recorded Braintrust trace through the evidence contract.

This adapter is test-only: it reads one recorded JSON fixture and performs
no authentication and no network access. It proves that downstream code
receives the same core contract from a second provider shape.
Production Braintrust support is a Phase 9 decision.
"""

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from app.domain.evidence.errors import TraceNotFound, TraceSourceUnavailable
from app.domain.evidence.mapping import SourceRun, normalize_runs
from app.domain.evidence.schemas import TraceEvidence
from app.domain.evidence.source import TraceQuery, evidence_matches_query

BRAINTRUST_FIXTURE = Path(__file__).parent / "fixtures" / "braintrust" / "phase2-01-equivalent.json"


def source_run_from_braintrust_span(span: Mapping[str, object]) -> SourceRun:
    """This function converts one Braintrust span into a neutral source run.

    Braintrust stores metrics (tokens, cost, latency) separately from span
    attributes. The function folds those metrics into canonical attribute
    names so normalization sees one provider-neutral shape.
    """
    span_id = span.get("id")
    if not isinstance(span_id, str) or not span_id:
        raise TraceSourceUnavailable()
    name = span.get("name")
    if not isinstance(name, str) or not name:
        raise TraceSourceUnavailable()
    attributes: dict[str, object] = {}
    span_attributes = span.get("span_attributes")
    if isinstance(span_attributes, dict):
        attributes.update(span_attributes)
    metrics = span.get("metrics")
    if isinstance(metrics, dict):
        tokens = metrics.get("tokens")
        if isinstance(tokens, dict):
            input_tokens = tokens.get("input")
            output_tokens = tokens.get("output")
            if isinstance(input_tokens, (int, float)):
                attributes["model.tokens.input"] = input_tokens
            if isinstance(output_tokens, (int, float)):
                attributes["model.tokens.output"] = output_tokens
            if "total" in tokens and isinstance(tokens["total"], (int, float)):
                attributes["model.tokens.total"] = tokens["total"]
            elif isinstance(input_tokens, (int, float)) and isinstance(output_tokens, (int, float)):
                attributes["model.tokens.total"] = input_tokens + output_tokens
        cost = metrics.get("cost")
        if isinstance(cost, dict) and isinstance(cost.get("usd"), (int, float)):
            attributes["model.cost.usd"] = cost["usd"]
        latency = metrics.get("latency")
        if isinstance(latency, dict) and isinstance(latency.get("ms"), (int, float)):
            attributes["model.latency.ms"] = latency["ms"]
    error = span.get("error")
    return SourceRun(
        run_id=span_id,
        name=name,
        parent_id=(
            str(span["parent_id"])
            if isinstance(span.get("parent_id"), str) and span["parent_id"]
            else None
        ),
        start_time=_parse_time(span.get("start_time")),
        end_time=_parse_time(span.get("end_time")),
        attributes=attributes,
        error=str(error) if isinstance(error, str) and error else None,
        trace_id=(
            str(span["trace_id"])
            if isinstance(span.get("trace_id"), str) and span["trace_id"]
            else None
        ),
    )


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise TraceSourceUnavailable()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TraceSourceUnavailable() from error


class BraintrustRecordedSource:
    """This class serves one recorded Braintrust trace from a JSON fixture."""

    def __init__(self, fixture_path: Path = BRAINTRUST_FIXTURE) -> None:
        self._fixture_path = fixture_path

    def _load_fixture(self) -> Mapping[str, object]:
        with self._fixture_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise TraceSourceUnavailable()
        return payload

    def _evidence(self, source_trace_id: str) -> TraceEvidence:
        fixture = self._load_fixture()
        recorded_trace_id = fixture.get("source_trace_id")
        if not isinstance(recorded_trace_id, str) or recorded_trace_id != source_trace_id:
            raise TraceNotFound()
        trace = fixture.get("trace")
        if not isinstance(trace, dict):
            raise TraceSourceUnavailable()
        spans = trace.get("spans")
        if not isinstance(spans, list):
            raise TraceSourceUnavailable()
        runs = [source_run_from_braintrust_span(span) for span in spans if isinstance(span, dict)]
        scenario_id = (
            str(fixture["scenario_id"]) if isinstance(fixture.get("scenario_id"), str) else None
        )
        project = str(fixture["project"]) if isinstance(fixture.get("project"), str) else None
        return normalize_runs(
            runs,
            platform="braintrust",
            project=project,
            scenario_id=scenario_id,
        )

    async def fetch_trace(self, source_trace_id: str) -> TraceEvidence:
        """This method returns the recorded Braintrust trace as evidence."""
        return self._evidence(source_trace_id)

    async def fetch_traces(self, query: TraceQuery) -> list[TraceEvidence]:
        """This method returns the recorded trace when it matches the query."""
        fixture = self._load_fixture()
        recorded_id = fixture.get("source_trace_id")
        if not isinstance(recorded_id, str):
            return []
        evidence = self._evidence(recorded_id)
        if not evidence_matches_query(evidence, query):
            return []
        return [evidence]
