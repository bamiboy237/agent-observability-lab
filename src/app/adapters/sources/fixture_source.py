"""This module provides a local fixture trace source for offline development.

The source reads versioned JSON fixtures that mimic recorded provider traces.
The source maps each fixture through the same normalization as live sources.
"""

import json
from collections.abc import Mapping
from pathlib import Path

from app.adapters.sources.langsmith import langsmith_run_url, source_run_from_langsmith
from app.domain.evidence.errors import TraceNotFound, TraceSourceUnavailable
from app.domain.evidence.mapping import normalize_runs
from app.domain.evidence.models import stable_evidence_id
from app.domain.evidence.schemas import TraceEvidence
from app.domain.evidence.source import TraceQuery, evidence_matches_query

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "langsmith"


class FixtureTraceSource:
    """This class serves selected traces and bounded cohorts from local fixtures.

    Each fixture file stores one recorded run tree plus its scenario metadata.
    Invalid fixtures surface their rejection error instead of loading.
    """

    def __init__(self, directory: Path = FIXTURE_DIRECTORY) -> None:
        self._directory = directory

    def _load_fixture(self, source_trace_id: str) -> Mapping[str, object]:
        fixture_path = self._directory / f"{source_trace_id}.json"
        if not fixture_path.is_file():
            raise TraceNotFound()
        with fixture_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise TraceSourceUnavailable()
        return payload

    def _evidence_for(self, source_trace_id: str) -> TraceEvidence:
        fixture = self._load_fixture(source_trace_id)
        trace = fixture.get("trace")
        if not isinstance(trace, dict):
            raise TraceSourceUnavailable()
        runs = [source_run_from_langsmith(run) for run in flatten_fixture_runs(trace)]
        scenario_id = (
            str(fixture["scenario_id"]) if isinstance(fixture.get("scenario_id"), str) else None
        )
        project = str(fixture["project"]) if isinstance(fixture.get("project"), str) else None
        budget_value = fixture.get("performance_budget_ms")
        budget_ms = (
            int(budget_value) if isinstance(budget_value, int) and budget_value > 0 else None
        )
        evidence = normalize_runs(
            runs,
            platform="langsmith",
            project=project,
            scenario_id=scenario_id,
            budget_ms=budget_ms,
        )
        source_url = langsmith_run_url(
            "https://smith.langchain.com",
            project or "fixture",
            source_trace_id,
            evidence.source.run_id or evidence.source.trace_id,
        )
        updated_source = evidence.source.model_copy(
            update={"trace_id": source_trace_id, "url": source_url}
        )
        return evidence.model_copy(
            update={
                "source": updated_source,
                "evidence_id": stable_evidence_id(updated_source),
            }
        )

    async def fetch_trace(self, source_trace_id: str) -> TraceEvidence:
        """This method returns one selected trace from a versioned fixture."""
        return self._evidence_for(source_trace_id)

    async def fetch_traces(self, query: TraceQuery) -> list[TraceEvidence]:
        """This method returns one explicit bounded cohort from local fixtures."""
        selected: list[TraceEvidence] = []
        for path in sorted(self._directory.glob("*.json")):
            if path.name.startswith("invalid-"):
                continue
            trace_id = path.stem
            evidence = self._evidence_for(trace_id)
            if not evidence_matches_query(evidence, query):
                continue
            selected.append(evidence)
            if len(selected) >= query.limit:
                break
        return selected

    def available_trace_ids(self) -> tuple[str, ...]:
        """This method lists the fixture trace ids available in this directory."""
        return tuple(
            sorted(
                path.stem
                for path in self._directory.glob("*.json")
                if not path.name.startswith("invalid-")
            )
        )


def flatten_fixture_runs(run: Mapping[str, object]) -> list[dict[str, object]]:
    """This function flattens one fixture run tree into pre-order (parents first)."""
    flattened: list[dict[str, object]] = []
    pending = [run]
    while pending:
        current = pending.pop(0)
        flattened.append(dict(current))
        children = current.get("child_runs")
        if isinstance(children, list):
            pending[0:0] = [dict(child) for child in children if isinstance(child, dict)]
    return flattened
