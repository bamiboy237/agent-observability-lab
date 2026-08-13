"""Generic flow contract for the user simulator.

This module deliberately contains no CLI and no support- or reference-specific
code.  It only defines the metadata/request/result contract, the
``FlowPlugin`` protocol, and a registry that fails on duplicate flow ids and
can lazily register optional built-in plugin factories.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.domain.user_simulator.events import EventSink
from app.domain.user_simulator.models import SimulatorReport

DEFAULT_MAX_TURNS = 12


@dataclass(frozen=True)
class FlowMetadata:
    """Display metadata for one registered flow."""

    flow_id: str
    case_id: str
    kind: str
    name: str = ""
    description: str = ""


@dataclass(frozen=True)
class RuntimeEnvironment:
    """Secret-safe runtime config resolved from the selected profile.

    Values are never logged or persisted; only field names are public.
    ``database_url`` is the selected profile's database URL (resolved from an
    environment variable at runtime), never a secret value literal.
    """

    environment: str = "test"
    database_url: str | None = None
    isolation_policy: str = "transaction-rollback"
    artifact_root: str = "artifacts/user-simulator"


@dataclass(frozen=True)
class FlowRunRequest:
    """Everything a plugin needs to run one flow.

    ``persona_context`` / ``script`` / ``goal`` carry optional wizard/flag
    overrides the adapter must apply to its persona.  ``runtime`` carries the
    resolved, secret-safe environment from the selected profile (for example
    the disposable database URL); adapters must use exactly that runtime and
    never fall back to unrelated configuration.
    """

    case_id: str
    max_turns: int = DEFAULT_MAX_TURNS
    root: Path = Path("artifacts/user-simulator")
    sink: EventSink | None = None
    persona_context: str | None = None
    script: str | None = None
    goal: str | None = None
    runtime: RuntimeEnvironment | None = None


@dataclass(frozen=True)
class FlowRunResult:
    """The stable result of one flow run."""

    report: SimulatorReport
    transcript_path: Path
    report_path: Path


@dataclass(frozen=True)
class FlowPersonaDefaults:
    """Persona context a plugin can expose for the setup wizard."""

    persona: str = ""
    script: str = ""
    goal: str = ""


@runtime_checkable
class FlowPlugin(Protocol):
    """One registered runnable flow.

    ``run`` is async end-to-end so cancellation reaches the plugin; adapters
    never wrap their own event loop.
    """

    metadata: FlowMetadata

    async def run(self, request: FlowRunRequest) -> FlowRunResult: ...


@runtime_checkable
class FlowPersonaProvider(Protocol):
    """Optional capability: expose default persona context for the wizard."""

    def persona_defaults(self) -> FlowPersonaDefaults: ...


@dataclass(frozen=True)
class ProjectedToolCall:
    """Display-safe projection of one tool call.

    ``safe`` means the projected arguments are safe to display.  Unknown
    tools fall back to a details-hidden label so argument values never leak
    through the timeline.
    """

    tool: str
    safe: bool
    label: str


@runtime_checkable
class ToolProjector(Protocol):
    """Projects one tool call and its result to display-safe text.

    Both projections must never leak argument values or unrestricted result
    text: unknown tools/results render as ``details hidden``.
    """

    def project(
        self, flow_id: str, tool: str, arguments: Mapping[str, object]
    ) -> ProjectedToolCall: ...

    def project_result(self, flow_id: str, tool: str, result: str) -> str: ...


class FlowRegistrationError(ValueError):
    """Raised when a plugin cannot be registered."""


class FlowNotFoundError(KeyError):
    """Raised when no plugin is registered for a flow id."""


class FlowRegistry:
    """Registers flow plugins and fails loudly on duplicate flow ids.

    Built-in plugin factories can be registered lazily and are materialized
    once, on first access, so importing the registry stays cheap.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, FlowPlugin] = {}
        self._builtin_factories: list[Callable[[], Iterable[FlowPlugin]]] = []

    def register(self, plugin: FlowPlugin) -> None:
        """Register one plugin; a duplicate flow id is a hard error."""
        if not hasattr(plugin, "metadata"):
            raise FlowRegistrationError("plugin must expose a FlowMetadata attribute")
        flow_id = plugin.metadata.flow_id
        if not flow_id:
            raise FlowRegistrationError("flow id must be a non-empty string")
        if flow_id in self._plugins:
            raise FlowRegistrationError(f"duplicate flow id: {flow_id}")
        self._plugins[flow_id] = plugin

    def register_builtin(self, factory: Callable[[], Iterable[FlowPlugin]]) -> None:
        """Register an optional factory that supplies built-in plugins lazily."""
        self._builtin_factories.append(factory)

    def ensure_builtins(self) -> None:
        """Materialize pending built-in factories exactly once."""
        if not self._builtin_factories:
            return
        factories = self._builtin_factories
        self._builtin_factories = []
        for factory in factories:
            for plugin in factory():
                self.register(plugin)

    def get(self, flow_id: str) -> FlowPlugin:
        """Return the plugin for one flow id or raise ``FlowNotFoundError``."""
        self.ensure_builtins()
        try:
            return self._plugins[flow_id]
        except KeyError:
            raise FlowNotFoundError(f"unknown flow: {flow_id}") from None

    def all(self) -> tuple[FlowPlugin, ...]:
        """Return every registered plugin in registration order."""
        self.ensure_builtins()
        return tuple(self._plugins.values())

    def contains(self, flow_id: str) -> bool:
        self.ensure_builtins()
        return flow_id in self._plugins

    def __len__(self) -> int:
        self.ensure_builtins()
        return len(self._plugins)
