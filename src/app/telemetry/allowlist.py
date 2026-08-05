"""This module defines the trace attribute allowlist and sanitizes attribute values.

The agent records only attributes in ``TRACE_ATTRIBUTE_ALLOWLIST`` on spans.
The agent, its tools, and telemetry helpers use this allowlist.
The :func:`sanitize_attributes` function drops every other attribute.
This module blocks secrets and unrestricted user text from traces.
"""

from collections.abc import Iterable, Mapping

MAX_ATTRIBUTE_VALUE_LENGTH = 256

TRACE_ATTRIBUTE_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Workflow and version metadata
        "agent.workflow.version",
        "agent.routing.instructions.version",
        "agent.answer.instructions.version",
        "agent.model.provider",
        "agent.model.name",
        # Turn outcome
        "support.intent",
        "support.confidence",
        "support.outcome",
        "support.reason.code",
        "support.policy.grounded",
        "support.message.length",
        "support.latency.ms",
        "support.tokens.input",
        "support.tokens.output",
        "support.tokens.total",
        "support.cost.usd",
        "support.retry.count",
        # Model call
        "model.latency.ms",
        "model.tokens.input",
        "model.tokens.output",
        "model.tokens.total",
        "model.cost.usd",
        "model.run.id",
        # Retrieval
        "retrieval.source",
        "retrieval.policy.slug",
        "retrieval.policy.version",
        "retrieval.latency.ms",
        # Tools
        "tool.name",
        "tool.order.id",
        "tool.latency.ms",
        "tool.error.code",
        # Database
        "db.operation",
        "db.latency.ms",
        "db.error.code",
        # Policy checks
        "policy.version",
        "policy.decision",
        "policy.reason.code",
        # Confirmation
        "confirmation.required",
        "confirmation.verified",
        # Escalation
        "escalation.ticket.id",
        "escalation.reason.code",
        # Scenario harness
        "scenario.id",
        "scenario.category",
        "scenario.cause",
        # Export metadata
        "langsmith.project",
        "service.name",
        "service.environment",
    }
)

_Scalar = bool | int | float | str


def sanitize_attributes(
    attributes: Mapping[str, object],
    forbidden_substrings: Iterable[str] = (),
) -> dict[str, _Scalar]:
    """This function keeps scalar values from the trace attribute allowlist.

    If a value contains forbidden text, this function drops the value.
    This function drops ``None``, non-scalar, empty, and overlong values.
    This function truncates strings to ``MAX_ATTRIBUTE_VALUE_LENGTH`` characters.
    """
    forbidden = tuple(substring for substring in forbidden_substrings if substring)
    sanitized: dict[str, _Scalar] = {}
    for key, value in attributes.items():
        if key not in TRACE_ATTRIBUTE_ALLOWLIST:
            continue
        if value is None:
            continue
        if isinstance(value, str):
            if not value:
                continue
            if any(substring in value for substring in forbidden):
                continue
            sanitized[key] = value[:MAX_ATTRIBUTE_VALUE_LENGTH]
        elif isinstance(value, (bool, int, float)):
            sanitized[key] = value
    return sanitized
