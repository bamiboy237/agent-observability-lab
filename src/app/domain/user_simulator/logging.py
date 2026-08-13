"""Continuous allowlisted JSONL logging for simulator runs."""

import json
from datetime import UTC, datetime
from pathlib import Path

_ALLOWED = frozenset(
    {
        "event",
        "run_id",
        "case_id",
        "turn",
        "message",
        "tool",
        "outcome",
        "reason",
        "error",
        "model_provider",
        "model_name",
        "tokens",
        "latency_ms",
    }
)


class JsonlEventLog:
    def __init__(
        self, run_id: str, case_id: str, root: Path = Path("artifacts/user-simulator")
    ) -> None:
        self.run_id, self.case_id = run_id, case_id
        self.path = root / f"{run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: object) -> None:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "run_id": self.run_id,
            "case_id": self.case_id,
        }
        for key, value in fields.items():
            if key not in _ALLOWED or not isinstance(value, (str, int, float, bool)):
                continue
            # Conversation text can contain identifiers or private customer data.
            # Keep the event shape without persisting unrestricted user text.
            payload[key] = "[redacted]" if key == "message" else value
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
            stream.flush()
