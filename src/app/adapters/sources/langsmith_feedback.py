"""Fixture-backed LangSmith annotation source adapter."""

import json
from pathlib import Path
from typing import Any

from app.domain.evidence.schemas import TraceEvidence
from app.domain.failures.feedback import FeedbackImportService
from app.domain.failures.schemas import FeedbackImportResult

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "langsmith_feedback" / "phase6-feedback.json"


class FixtureLangSmithFeedbackSource:
    """Read local LangSmith-shaped annotations for offline imports."""

    def __init__(self, path: Path = FIXTURE_PATH) -> None:
        self._path = path

    def _load(self) -> list[dict[str, Any]]:
        with self._path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError("LangSmith feedback fixture must be a list of objects")
        return payload

    def annotations_for(self, trace_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(item for item in self._load() if item.get("trace_id") == trace_id)

    async def import_for_trace(
        self,
        evidence: TraceEvidence,
        service: FeedbackImportService,
    ) -> tuple[FeedbackImportResult, ...]:
        return tuple(
            [
                await service.import_annotation(
                    raw,
                    evidence,
                    platform="langsmith",
                    project="agent-reliability-lab",
                )
                for raw in self.annotations_for(evidence.source.trace_id)
            ]
        )


__all__ = ["FixtureLangSmithFeedbackSource"]
