"""Structured application logging."""

import json
import logging
from datetime import UTC, datetime

REQUEST_LOGGER_NAME = "app.request"
REQUEST_LOG_FIELDS = ("request_id", "method", "path", "status_code", "duration_ms")


class JsonFormatter(logging.Formatter):
    """Format application log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in REQUEST_LOG_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload)


request_logger = logging.getLogger(REQUEST_LOGGER_NAME)


def configure_logging() -> None:
    """Configure the request logger once per process."""
    if not request_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        request_logger.addHandler(handler)
    request_logger.setLevel(logging.INFO)
    request_logger.propagate = False
