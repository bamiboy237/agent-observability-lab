"""This module implements the single-bundle simulation runner.

The runner loads one validated bundle, reconstructs the safe request and the
synthetic state, provisions a disposable environment, runs the real hosted
model and the real agent workflow against the real support services and
PostgreSQL sandbox, applies approved fixtures and fault scripts, captures
the final state and the normalized transcript, and destroys or rolls back
the environment. Retention is rejected until a retention manager exists,
because a retained environment would be an unreachable open transaction.
The run result distinguishes reproduced behavior, accepted behavior, failed
behavior, unexpected access, and missing coverage, and the runner returns
safe typed errors for invalid bundles, missing coverage, environment
failures, model failures, and cleanup failures.
"""

import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from time import perf_counter
from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.pydantic_ai_agent import ModelConfig, PydanticAISupportAgent
from app.domain.agent.instructions import (
    ANSWER_INSTRUCTIONS,
    ANSWER_INSTRUCTIONS_VERSION,
)
from app.domain.agent.schemas import (
    ReasonCode,
    RouteIntent,
    SupportOutcome,
    SupportRequest,
    SupportResponse,
)
from app.domain.bundle.errors import MissingCoverageError
from app.domain.bundle.schemas import SimulationBundle, fixtures_by_dependency, resources_by_type
from app.domain.comparison.evaluators import (
    ALL_EVALUATORS,
    Evaluator,
    EvaluatorReport,
    RunMetrics,
    run_evaluators,
)
from app.domain.evidence.schemas import TraceSourceRef
from app.domain.simulation.adapters import (
    DependencyAdapter,
    SimulationAdapterRegistry,
    StateMutation,
    normalize_arguments,
    requirement_is_covered,
)
from app.domain.simulation.errors import (
    CleanupRunError,
    EnvironmentRunError,
    InvalidSimulationBundleError,
    MalformedResponseError,
    MissingSimulationCoverageError,
    ModelRunError,
    RetentionUnavailableError,
    UnsupportedArgumentsError,
    UnsupportedStateError,
    UnsupportedToolError,
)
from app.domain.simulation.events import (
    SIMULATION_EVENT_ATTRIBUTE_ALLOWLIST,
    SimulationEvent,
    SimulationEventCollector,
    SimulationEventKind,
)
from app.domain.simulation.provisioner import (
    EnvironmentRequest,
    ProvisionerFactory,
    RetentionInfo,
    RetentionRequest,
)
from app.domain.simulation.recorded import RecordedProviderResponse, RecordedReadAdapter
from app.domain.simulation.schemas import SimulationScenario, SimulationState
from app.domain.support.schemas import (
    OrderRead,
    OrderStatus,
    PolicyDocumentRead,
    TicketRead,
    TicketStatus,
)
from app.errors import DomainError
from app.telemetry.recorder import TraceRecorder, TraceSpan

SIMULATION_RUN_SCHEMA_VERSION = "1.0.0"

Scalar = bool | int | float | str

_OWNED_DATABASE = "support.database"
_TOOL_SPAN_PREFIX = "support_agent.tool."


class RunVerdict(StrEnum):
    """This enum classifies one completed run.

    ``reproduced`` means the outcome, reason, and policy grounding match the
    reviewed expectation. ``accepted`` means the outcome matches but the run
    took a different safe path. ``failed`` means the outcome does not match.
    ``unexpected_access`` and ``missing_coverage`` classify runs that a
    dependency boundary or the environment could not serve.
    """

    REPRODUCED = "reproduced"
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNEXPECTED_ACCESS = "unexpected_access"
    MISSING_COVERAGE = "missing_coverage"


class SimulationRun(BaseModel):
    """This class stores one normalized simulation run transcript."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=SIMULATION_RUN_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    run_id: UUID
    bundle_id: UUID
    bundle_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str
    evidence_ref: TraceSourceRef | None = None
    evidence_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    verdict: RunVerdict
    response: SupportResponse | None = None
    events: tuple[SimulationEvent, ...] = ()
    mutations: tuple[StateMutation, ...] = ()
    final_state: SimulationState
    evaluators: EvaluatorReport = Field(default_factory=EvaluatorReport)
    model_provider: str | None = None
    model_name: str | None = None
    total_latency_ms: float | None = Field(default=None, ge=0)
    model_latency_ms: float | None = Field(default=None, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    retries: int = Field(default=0, ge=0)
    tool_calls: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    retention: RetentionInfo | None = None
    completed_at: str = Field(min_length=1, max_length=100)


def state_from_bundle(bundle: SimulationBundle) -> SimulationState:
    """This function reconstructs the synthetic disposable state from the seeds."""
    resources = resources_by_type(bundle)
    orders = tuple(
        OrderRead(
            id=UUID(str(record["id"])),
            customer_id=UUID(str(record["customer_id"])),
            status=OrderStatus(str(record["status"])),
            total_amount=Decimal(str(record["total_amount"])),
        )
        for record in resources.get("order", ())
    )
    tickets = tuple(
        TicketRead(
            id=UUID(str(record["id"])),
            customer_id=UUID(str(record["customer_id"])),
            order_id=UUID(str(record["order_id"])) if record.get("order_id") else None,
            subject=str(record["subject"]),
            status=TicketStatus(str(record["status"])),
        )
        for record in resources.get("ticket", ())
    )
    policies = tuple(
        PolicyDocumentRead(
            id=UUID(str(record["id"])),
            slug=str(record["slug"]),
            version=str(record["version"]),
            title=str(record["title"]),
            content=str(record["content"]),
            content_hash=str(record["content_hash"]),
        )
        for record in resources.get("policy", ())
    )
    return SimulationState(orders=orders, tickets=tickets, policies=policies)


def scenario_from_bundle(bundle: SimulationBundle) -> SimulationScenario:
    """This function reconstructs the runnable scenario from one bundle.

    The request, the synthetic state, and the expected behavior all come from
    the bundle, so the same bundle always reconstructs the same starting
    conditions.
    """
    scenario = bundle.scenario
    return SimulationScenario(
        schema_version=scenario.source_schema_version,
        scenario_id=scenario.scenario_id,
        title=f"Simulated {scenario.scenario_id}",
        category=scenario.category,
        request=SupportRequest(
            customer_id=scenario.request.customer_id,
            message=scenario.request.message,
            refund_confirmed=scenario.request.refund_confirmed,
        ),
        workflow_context=scenario.workflow_context,
        initial_state=state_from_bundle(bundle),
        eligible_actions=scenario.eligible_actions,
        expected_behavior=bundle.expected_behavior,
        required_dependency_coverage=scenario.required_dependency_coverage,
    )


class _Metrics:
    """This class accumulates the normalized measurements of one run."""

    def __init__(self) -> None:
        self.model_latency_ms = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.cost_usd: float | None = None
        self.retries = 0
        self.tool_calls: list[str] = []
        self.tool_errors: list[str] = []
        self.retrieved_policy_version: str | None = None
        self.policy_grounded: bool | None = None


def _pick(attributes: Mapping[str, object], *keys: str) -> dict[str, Scalar]:
    """This function keeps only allowlisted scalar attributes for events."""
    picked: dict[str, Scalar] = {}
    for key in keys:
        if key not in attributes or key not in SIMULATION_EVENT_ATTRIBUTE_ALLOWLIST:
            continue
        value = attributes[key]
        if value is None or not isinstance(value, (bool, int, float, str)):
            continue
        picked[key] = value
    return picked


class _SpanEventMapper:
    """This class maps agent spans to normalized simulation events.

    The mapper runs inside the recorder listener, so the events stream while
    the agent executes and carry only allowlisted attributes: model metadata,
    tool names, safe argument identifiers, error codes, and timings. Secret
    reasoning and raw payloads never enter spans, so they never enter events.
    """

    def __init__(
        self,
        collector: SimulationEventCollector,
        metrics: _Metrics,
        model_provider: str | None,
        model_name: str | None,
    ) -> None:
        self._collector = collector
        self._metrics = metrics
        self._model_provider = model_provider
        self._model_name = model_name

    def __call__(self, span: TraceSpan, ended: bool) -> None:
        name = span.name
        if name in ("support_agent.routing", "support_agent.answer"):
            if not ended:
                request_attributes: dict[str, Scalar] = {}
                if self._model_provider is not None:
                    request_attributes["model.provider"] = self._model_provider
                if self._model_name is not None:
                    request_attributes["model.name"] = self._model_name
                self._collector.emit(SimulationEventKind.MODEL_REQUEST, request_attributes)
            else:
                attributes = _pick(
                    span.attributes,
                    "model.latency.ms",
                    "model.tokens.input",
                    "model.tokens.output",
                    "model.tokens.total",
                    "model.cost.usd",
                    "model.run.id",
                )
                self._collector.emit(SimulationEventKind.MODEL_RESPONSE, attributes)
                self._accumulate_model(attributes)
        elif name.startswith(_TOOL_SPAN_PREFIX):
            tool = name[len(_TOOL_SPAN_PREFIX) :]
            if not ended:
                self._collector.emit(SimulationEventKind.TOOL_SELECTED, {"tool": tool})
            else:
                tool_attributes: dict[str, Scalar] = {"tool": tool}
                tool_attributes.update(_pick(span.attributes, "tool.order.id"))
                error = span.error_code or span.attributes.get("tool.error.code")
                if error is not None:
                    tool_attributes["tool.error.code"] = str(error)
                self._collector.emit(SimulationEventKind.DEPENDENCY_RESULT, tool_attributes)
                self._metrics.tool_calls.append(tool)
                if error is not None:
                    self._metrics.tool_errors.append(str(error))
        elif name == "support_agent.retry" and ended:
            count = span.attributes.get("support.retry.count", self._metrics.retries + 1)
            self._collector.emit(SimulationEventKind.RETRY, {"retry.count": count})
            self._metrics.retries += 1
        elif name == "support_agent.database.read" and ended:
            db_attributes = _pick(
                span.attributes,
                "db.operation",
                "db.latency.ms",
                "db.error.code",
            )
            if db_attributes:
                self._collector.emit(SimulationEventKind.DEPENDENCY_RESULT, db_attributes)
        elif name == "support_agent.retrieval.policy" and ended:
            retrieval_attributes = _pick(span.attributes, "retrieval.policy.version")
            if retrieval_attributes:
                self._collector.emit(SimulationEventKind.DEPENDENCY_RESULT, retrieval_attributes)
                version = retrieval_attributes.get("retrieval.policy.version")
                if isinstance(version, str):
                    self._metrics.retrieved_policy_version = version
        elif name == "support_agent.turn" and ended:
            grounded = span.attributes.get("support.policy.grounded")
            if isinstance(grounded, bool):
                self._metrics.policy_grounded = grounded

    def _accumulate_model(self, attributes: Mapping[str, object]) -> None:
        latency = attributes.get("model.latency.ms")
        if isinstance(latency, (int, float)):
            self._metrics.model_latency_ms += float(latency)
        for field, target in (
            ("model.tokens.input", "input_tokens"),
            ("model.tokens.output", "output_tokens"),
            ("model.tokens.total", "total_tokens"),
        ):
            value = attributes.get(field)
            if isinstance(value, (int, float)):
                setattr(self._metrics, target, getattr(self._metrics, target) + int(value))
        cost = attributes.get("model.cost.usd")
        if isinstance(cost, (int, float)):
            self._metrics.cost_usd = (self._metrics.cost_usd or 0.0) + float(cost)


def _verdict(
    bundle: SimulationBundle,
    metrics: RunMetrics,
    aborted: RunVerdict | None,
) -> RunVerdict:
    if aborted is not None:
        return aborted
    expected = bundle.expected_behavior
    outcome_matches = metrics.outcome is expected.outcome
    reason_matches = metrics.reason_code in expected.reason_codes
    grounded_matches = (
        expected.policy_grounded is None or metrics.policy_grounded == expected.policy_grounded
    )
    if outcome_matches and reason_matches and grounded_matches:
        return RunVerdict.REPRODUCED
    if outcome_matches:
        return RunVerdict.ACCEPTED
    return RunVerdict.FAILED


async def _recorded_adapters_from_bundle(
    bundle: SimulationBundle,
) -> tuple[RecordedReadAdapter, ...]:
    """This function builds recorded adapters from the bundle fixtures.

    Recorded fixtures never replace the owned database: fixtures for
    ``support.database`` are rejected before any adapter is built.
    """
    if any(fixture.dependency == _OWNED_DATABASE for fixture in bundle.dependency_fixtures):
        raise InvalidSimulationBundleError(
            detail=(
                "recorded fixtures must not replace support.database; owned-system "
                "state must use stateful environment seeds"
            )
        )
    adapters: list[RecordedReadAdapter] = []
    for dependency, fixtures in fixtures_by_dependency(bundle).items():
        captured: dict[str, dict[str, dict[str, object]]] = {}
        for fixture in fixtures:
            key = normalize_arguments(fixture.arguments)
            captured.setdefault(fixture.tool, {})[key] = {
                "payload": fixture.payload,
                "error_code": fixture.error_code,
                "malformed": fixture.malformed,
            }
        tools = tuple(sorted(captured))
        adapter = RecordedProviderResponse(dependency, tools)
        await adapter.sanitize(captured)
        adapters.append(adapter)
    return tuple(adapters)


def _metrics_for(
    metrics: _Metrics,
    response: SupportResponse | None,
    total_latency_ms: float | None,
    mutations: tuple[StateMutation, ...],
) -> RunMetrics:
    reason = response.reason_code if response is not None else ReasonCode.TOOL_ERROR
    return RunMetrics(
        outcome=response.outcome if response is not None else SupportOutcome.FAILED,
        reason_code=reason,
        intent=response.intent if response is not None else RouteIntent.ESCALATE,
        tool_calls=tuple(metrics.tool_calls),
        tool_errors=tuple(metrics.tool_errors),
        retries=metrics.retries,
        total_latency_ms=total_latency_ms,
        model_latency_ms=round(metrics.model_latency_ms, 2),
        tokens=metrics.total_tokens,
        cost_usd=metrics.cost_usd,
        mutations=mutations,
        policy_grounded=metrics.policy_grounded,
        retrieved_policy_version=metrics.retrieved_policy_version,
    )


def _clean_attributes(attributes: Mapping[str, object]) -> dict[str, Scalar]:
    """This function drops None and non-scalar values for event attributes."""
    cleaned: dict[str, Scalar] = {}
    for key, value in attributes.items():
        if value is None or not isinstance(value, (bool, int, float, str)):
            continue
        cleaned[key] = value
    return cleaned


def _reject_unreachable_dependencies(
    scenario: SimulationScenario,
    bundle: SimulationBundle,
) -> None:
    """This function rejects dependencies the reference agent cannot reach.

    The reference agent is wired only to the owned ``support.database``
    repository. Declared external dependencies and recorded fixtures would
    satisfy the coverage report but could never serve a call during
    execution, so the bundle is rejected before any environment is created.
    """
    for requirement in scenario.required_dependency_coverage:
        if requirement.dependency == _OWNED_DATABASE:
            continue
        raise InvalidSimulationBundleError(
            detail=(
                f"the reference agent cannot use declared dependency "
                f"{requirement.dependency!r} during execution; the reference agent "
                "is wired only to the owned support.database"
            )
        )
    for fixture in bundle.dependency_fixtures:
        if fixture.dependency == _OWNED_DATABASE:
            continue
        raise InvalidSimulationBundleError(
            detail=(
                f"recorded fixtures for dependency {fixture.dependency!r} cannot "
                "reach the reference agent during execution; the reference agent "
                "is wired only to the owned support.database"
            )
        )


def _reject_invalid_fault_boundary(bundle: SimulationBundle) -> None:
    """This function rejects fault scripts that name the wrong boundary.

    A fault script must target exactly the environment that receives it.
    The runner provisions only ``support.database``, so a script declared
    for any other dependency is rejected instead of being applied to the
    wrong boundary.
    """
    script = bundle.fault_script
    if script is not None and script.entries and script.dependency != _OWNED_DATABASE:
        raise InvalidSimulationBundleError(
            detail=(
                f"fault script targets dependency {script.dependency!r}, but the "
                f"run environment is {_OWNED_DATABASE!r}; a fault script may only "
                "wrap the environment that receives it"
            )
        )


async def run_bundle(
    *,
    bundle: SimulationBundle,
    provisioner_factory: ProvisionerFactory,
    model_config: ModelConfig,
    collector: SimulationEventCollector | None = None,
    retention: RetentionRequest | None = None,
    answer_instructions: str = ANSWER_INSTRUCTIONS,
    answer_instructions_version: str | None = None,
    tools_override: tuple[str, ...] | None = None,
    evaluators: Sequence[Evaluator] = ALL_EVALUATORS,
) -> SimulationRun:
    """This function runs one validated bundle inside a disposable environment.

    The bundle must already be validated. The provisioner factory receives
    the reconstructed scenario, the bundle fault script, and the event sink.
    The environment is always destroyed or rolled back; retention requests
    are rejected before provisioning until a retention manager exists.
    Errors are safe typed errors.
    """
    if bundle.bundle_id is None or bundle.content_hash is None:
        raise InvalidSimulationBundleError(
            detail="bundle has no derived identifier or content hash"
        )
    if retention is not None:
        raise RetentionUnavailableError(
            detail=(
                "no retention manager exists yet; a retained environment would be "
                "an unreachable open transaction that could leak a database session. "
                "Destroy the environment after the run instead."
            )
        )
    collector = collector or SimulationEventCollector()
    try:
        scenario = scenario_from_bundle(bundle)
    except ValidationError as error:
        raise InvalidSimulationBundleError(
            detail=f"bundle cannot reconstruct a scenario: {error}"
        ) from error
    _reject_invalid_fault_boundary(bundle)
    _reject_unreachable_dependencies(scenario, bundle)

    recorded = await _recorded_adapters_from_bundle(bundle)
    provisioner = provisioner_factory(
        EnvironmentRequest(
            scenario=scenario,
            fault_script=bundle.fault_script,
            sink=collector,
        )
    )

    registry = SimulationAdapterRegistry(
        (
            cast(DependencyAdapter, provisioner),
            *(cast(DependencyAdapter, adapter) for adapter in recorded),
        )
    )
    missing = tuple(
        requirement.dependency
        for requirement in scenario.required_dependency_coverage
        if not requirement_is_covered(requirement, registry.coverage_items())
    )
    if missing:
        raise MissingCoverageError(scenario_id=scenario.scenario_id, missing=missing)

    metrics = _Metrics()
    mapper = _SpanEventMapper(collector, metrics, model_config.provider, model_config.name)
    recorder = TraceRecorder(None, span_listener=mapper)
    instructions_version = (
        answer_instructions_version
        or bundle.configuration_versions.answer_instructions_version
        or ANSWER_INSTRUCTIONS_VERSION
    )

    aborted: RunVerdict | None = None
    response: SupportResponse | None = None
    total_latency_ms: float | None = None
    mutations: tuple[StateMutation, ...] = ()
    final_state: SimulationState | None = None
    retention_info: RetentionInfo | None = None
    report: EvaluatorReport | None = None
    verdict: RunVerdict | None = None
    errors: tuple[str, ...] = ()

    try:
        try:
            await provisioner.create()
            await provisioner.seed(scenario.initial_state)
            repository = provisioner.connect()

            request = SupportRequest(
                customer_id=bundle.scenario.request.customer_id,
                message=bundle.scenario.request.message,
                refund_confirmed=bundle.scenario.request.refund_confirmed,
            )
            agent = PydanticAISupportAgent(
                model_config=model_config,
                recorder=recorder,
                repository=repository,
                answer_instructions=answer_instructions,
                answer_instructions_version=instructions_version,
                tools_override=tools_override,
            )
            started = perf_counter()
            try:
                response = await agent.handle(request)
                total_latency_ms = round((perf_counter() - started) * 1000, 2)
            except (
                UnsupportedToolError,
                UnsupportedArgumentsError,
                UnsupportedStateError,
                MalformedResponseError,
            ):
                aborted = RunVerdict.UNEXPECTED_ACCESS
            except MissingSimulationCoverageError:
                aborted = RunVerdict.MISSING_COVERAGE
            except DomainError:
                raise
            except Exception as error:
                raise ModelRunError(detail=str(error)) from error

            final_state = await provisioner.final_state()
            mutations = provisioner.mutations()
        except DomainError:
            raise
        except Exception as error:
            raise EnvironmentRunError(detail=str(error)) from error

        run_metrics = _metrics_for(metrics, response, total_latency_ms, mutations)
        report = (
            run_evaluators(bundle, run_metrics, evaluators)
            if response is not None and aborted is None
            else EvaluatorReport()
        )
        verdict = _verdict(bundle, run_metrics, aborted)

        for result in report.results:
            collector.emit(
                SimulationEventKind.EVALUATOR_RESULT,
                _clean_attributes(
                    {
                        "evaluator": result.evaluator,
                        "evaluator.version": result.version,
                        "evaluator.passed": result.passed,
                        "evaluator.reason": result.reason[:256],
                    }
                ),
            )
        error_codes: set[str] = set()
        if aborted is not None:
            error_codes.add(aborted.value)
        if response is not None and response.outcome is SupportOutcome.FAILED:
            error_codes.add("model_error")
        errors = tuple(sorted(error_codes))
        collector.emit(
            SimulationEventKind.RUN_COMPLETED,
            _clean_attributes(
                {
                    "run.verdict": verdict.value,
                    "run.total.latency.ms": round(total_latency_ms, 2)
                    if total_latency_ms is not None
                    else None,
                    "run.model.latency.ms": round(metrics.model_latency_ms, 2),
                    "run.tokens.input": metrics.input_tokens,
                    "run.tokens.output": metrics.output_tokens,
                    "run.tokens.total": metrics.total_tokens,
                    "run.cost.usd": metrics.cost_usd,
                    "run.retries": metrics.retries,
                    "run.errors": ",".join(errors),
                }
            ),
        )
    finally:
        pending = sys.exc_info()[0]
        try:
            await provisioner.destroy()
        except Exception as error:
            if pending is None:
                raise CleanupRunError(detail=str(error)) from error

    if final_state is None or report is None or verdict is None:
        raise EnvironmentRunError(detail="the environment did not produce a final state")

    return SimulationRun(
        run_id=uuid4(),
        bundle_id=bundle.bundle_id,
        bundle_content_hash=bundle.content_hash,
        scenario_id=bundle.scenario.scenario_id,
        evidence_ref=bundle.evidence_ref,
        evidence_content_hash=bundle.evidence_content_hash,
        verdict=verdict,
        response=response,
        events=collector.events(),
        mutations=mutations,
        final_state=final_state,
        evaluators=report,
        model_provider=model_config.provider,
        model_name=model_config.name,
        total_latency_ms=total_latency_ms,
        model_latency_ms=round(metrics.model_latency_ms, 2),
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
        total_tokens=metrics.total_tokens,
        cost_usd=metrics.cost_usd,
        retries=metrics.retries,
        tool_calls=tuple(metrics.tool_calls),
        errors=errors,
        retention=retention_info,
        completed_at=datetime.now(UTC).isoformat(),
    )
