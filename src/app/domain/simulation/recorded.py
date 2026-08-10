"""This module implements recorded-read simulation adapters.

A recorded adapter replays approved captured responses for order lookup,
policy retrieval, provider responses, and clock values. Requests match by
tool name and normalized arguments. Unexpected access fails closed: the
adapter never invents a plausible response. Scripted entries reproduce
timeout and malformed-response cases in order.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.bundle.allowlist import SENSITIVE_KEY_PARTS
from app.domain.simulation.adapters import (
    AdapterKind,
    DependencyCallResult,
    StateMutation,
    normalize_arguments,
)
from app.domain.simulation.errors import (
    InvalidSimulationFixture,
    UnsupportedArgumentsError,
    UnsupportedToolError,
)
from app.domain.simulation.schemas import SimulationState


@dataclass(frozen=True)
class RecordedResponse:
    """This class stores one approved response that a recorded adapter replays."""

    payload: object | None = None
    error_code: str | None = None
    malformed: bool = False


def _contains_sensitive_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                return True
            if _contains_sensitive_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(nested) for nested in value)
    return False


def _json_safe(value: object) -> bool:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def sanitize_captured_data(
    captured: Mapping[str, object],
    *,
    supported_tools: Sequence[str],
) -> dict[str, dict[str, list[RecordedResponse]]]:
    """This function turns approved captured data into a recorded table.

    Unknown tools, non-scalar argument keys, sensitive payload keys, and
    non-JSON payloads fail closed. Only the sanitized table is replayed.
    """
    table: dict[str, dict[str, list[RecordedResponse]]] = {}
    for tool_name, entries in captured.items():
        if tool_name not in supported_tools:
            raise InvalidSimulationFixture(
                detail=f"tool {tool_name!r} is not offered by this adapter"
            )
        if not isinstance(entries, dict):
            raise InvalidSimulationFixture(detail=f"tool {tool_name!r} has no argument table")
        tool_table: dict[str, list[RecordedResponse]] = {}
        for arguments_key, raw in entries.items():
            if not isinstance(arguments_key, str):
                raise InvalidSimulationFixture(
                    detail=f"tool {tool_name!r} has a non-string arguments key"
                )
            try:
                normalized = json.loads(arguments_key)
            except ValueError as error:
                raise InvalidSimulationFixture(
                    detail=f"tool {tool_name!r} has an unparseable arguments key"
                ) from error
            if not isinstance(normalized, dict):
                raise InvalidSimulationFixture(
                    detail=f"tool {tool_name!r} has a non-object arguments key"
                )
            responses = raw if isinstance(raw, list) else [raw]
            parsed: list[RecordedResponse] = []
            for entry in responses:
                if not isinstance(entry, dict):
                    raise InvalidSimulationFixture(
                        detail=f"tool {tool_name!r} has a non-object recorded response"
                    )
                payload = entry.get("payload")
                error_code = entry.get("error_code")
                malformed = entry.get("malformed", False)
                if payload is not None and not _json_safe(payload):
                    raise InvalidSimulationFixture(
                        detail=f"tool {tool_name!r} has a non-JSON payload"
                    )
                if _contains_sensitive_key(payload):
                    raise InvalidSimulationFixture(
                        detail=f"tool {tool_name!r} records a sensitive payload key"
                    )
                if error_code is not None and not isinstance(error_code, str):
                    raise InvalidSimulationFixture(
                        detail=f"tool {tool_name!r} has a non-string error code"
                    )
                if not isinstance(malformed, bool):
                    raise InvalidSimulationFixture(
                        detail=f"tool {tool_name!r} has a non-boolean malformed flag"
                    )
                parsed.append(
                    RecordedResponse(
                        payload=payload,
                        error_code=error_code,
                        malformed=malformed,
                    )
                )
            tool_table[arguments_key] = parsed
        table[tool_name] = tool_table
    return table


class RecordedReadAdapter:
    """This base class replays approved responses for one dependency.

    Requests match by tool name and normalized arguments. A script of
    responses for the same arguments replays in order, so a first-timeout
    second-success case reproduces exactly. Reset restarts every script.
    """

    kind: AdapterKind = "recorded"
    dependency_name: str
    supported_tool_names: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._table: dict[str, dict[str, list[RecordedResponse]]] = {}
        self._consumed: dict[tuple[str, str], int] = {}

    async def sanitize(self, captured: Mapping[str, object]) -> None:
        """This method loads approved captured data after strict sanitization."""
        self._table = sanitize_captured_data(
            captured,
            supported_tools=self.supported_tool_names,
        )
        self._consumed = {}

    async def seed(self, state: SimulationState) -> None:
        """Recorded reads carry no state; seeding is a no-op."""

    async def reset(self) -> None:
        """This method restarts every response script from its first entry."""
        self._consumed = {}

    def supported_tools(self) -> tuple[str, ...]:
        return self.supported_tool_names

    def state_transitions(self) -> tuple[str, ...]:
        return ()

    def mutations(self) -> tuple[StateMutation, ...]:
        return ()

    async def call(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> DependencyCallResult:
        """This method replays one recorded response or fails closed."""
        if tool_name not in self.supported_tool_names:
            raise UnsupportedToolError(dependency=self.dependency_name, tool=tool_name)
        try:
            arguments_key = normalize_arguments(arguments)
        except UnsupportedArgumentsError as error:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=dict(arguments),
            ) from error
        script = self._table.get(tool_name, {}).get(arguments_key)
        if not script:
            raise UnsupportedArgumentsError(
                dependency=self.dependency_name,
                tool=tool_name,
                arguments=dict(arguments),
            )
        position = self._consumed.get((tool_name, arguments_key), 0)
        response = script[min(position, len(script) - 1)]
        self._consumed[(tool_name, arguments_key)] = position + 1
        if response.malformed:
            return DependencyCallResult(ok=False, error_code="malformed_response")
        if response.error_code is not None:
            return DependencyCallResult(ok=False, error_code=response.error_code)
        return DependencyCallResult(ok=True, payload=response.payload)


class RecordedOrderLookup(RecordedReadAdapter):
    """This adapter replays approved order lookup responses.

    Tool ``get_order_status`` takes one normalized argument: the order id.
    Scripted error entries reproduce order_not_found and timeout cases.
    """

    dependency_name = "order.lookup"
    supported_tool_names = ("get_order_status",)


class RecordedPolicyRetrieval(RecordedReadAdapter):
    """This adapter replays approved policy retrieval responses.

    Tool ``get_policy`` takes the policy slug and an optional version.
    A stale policy version reproduces the wrong-evidence scenario.
    """

    dependency_name = "policy.retrieval"
    supported_tool_names = ("get_policy",)


class RecordedProviderResponse(RecordedReadAdapter):
    """This adapter replays approved responses from an external provider.

    The adapter is generic: construction supplies the dependency name and
    the recorded tool names. No network access ever occurs during replay.
    """

    def __init__(self, dependency: str, tools: Sequence[str]) -> None:
        super().__init__()
        self.dependency_name = dependency
        self.supported_tool_names = tuple(tools)


class RecordedClock(RecordedReadAdapter):
    """This adapter replays approved clock values.

    Tool ``clock.now`` returns the recorded timestamp with no arguments.
    A fixed clock keeps time-dependent behavior deterministic.
    """

    dependency_name = "clock"
    supported_tool_names = ("clock.now",)
