"""This module runs the eight fixed Phase 2 scenarios with a hosted model.

The harness applies the state that reproduces each scenario.
The harness checks that the agent returns a valid typed response and an outcome other than failed.
The harness checks trace evidence.
The harness checks that order state stays unchanged.
The harness checks that traces contain no private data.
The harness and the model produce the cause of failure.
Deterministic checks enforce the safety guarantees.
"""

import asyncio
import os
from collections.abc import Callable
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.adapters.pydantic_ai_agent import ModelConfig, PydanticAISupportAgent
from app.domain.agent.scenarios import SCENARIOS, ScenarioDefinition
from app.domain.agent.schemas import ReasonCode, SupportOutcome, SupportResponse
from app.domain.support.schemas import OrderRead, PolicyDocumentRead
from app.telemetry.recorder import TraceRecorder
from tests.fakes.support_repository import InMemorySupportRepository
from tests.live.conftest import build_live_repository

BAD_ANSWER_INSTRUCTIONS = (
    "You are a support agent. Answer policy questions from your general "
    "knowledge about refunds and returns. Do not call any tools. Answer in "
    "two short sentences."
)

STALE_POLICY = PolicyDocumentRead(
    id=UUID("99999999-0000-4000-8000-000000000001"),
    slug="refund-and-delivery",
    version="2025-01-01",
    title="Refund and Delivery Policy",
    content=(
        "# Refund and Delivery Policy\n\n"
        "Policy version: 2025-01-01\n\n"
        "Any order may be refunded at any time, for any reason, in cash.\n"
    ),
    content_hash="stale-hash",
)


class FlakyRepository(InMemorySupportRepository):
    """This repository fails its first read or delays every read."""

    def __init__(
        self,
        *,
        fail_first_read: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        base = build_live_repository()
        super().__init__(orders=tuple(base.orders.values()), policies=tuple(base.policies.values()))
        self._fail_first_read = fail_first_read
        self._delay_seconds = delay_seconds
        self.read_count = 0

    async def get_order(self, order_id: UUID) -> OrderRead | None:
        self.read_count += 1
        if self._fail_first_read and self.read_count == 1:
            raise TimeoutError("simulated upstream timeout")
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return await super().get_order(order_id)


def all_attributes(exporter: InMemorySpanExporter) -> dict[str, object]:
    attributes: dict[str, object] = {}
    for span in exporter.get_finished_spans():
        attributes.update(span.attributes or {})
    return attributes


def span_names(exporter: InMemorySpanExporter) -> list[str]:
    return [span.name for span in exporter.get_finished_spans()]


def _harness_for(scenario: ScenarioDefinition) -> dict[str, object]:
    """This function returns arguments for the adapter.

    The arguments reproduce the scenario.
    """
    if scenario.scenario_id == "phase2-01-bad-prompt-policy-answer":
        return {
            "answer_instructions": BAD_ANSWER_INSTRUCTIONS,
            "answer_instructions_version": "0-bad",
        }
    return {}


def _repository_for(scenario: ScenarioDefinition) -> InMemorySupportRepository:
    if scenario.scenario_id == "phase2-02-wrong-policy-evidence":
        base = build_live_repository()
        return InMemorySupportRepository(
            orders=tuple(base.orders.values()),
            policies=(STALE_POLICY,),
        )
    if scenario.scenario_id in ("phase2-03-database-timeout", "phase2-06-repeated-step"):
        return FlakyRepository(fail_first_read=True)
    if scenario.scenario_id == "phase2-07-slow-database":
        return FlakyRepository(delay_seconds=2.5)
    return build_live_repository()


def _require_evidence(scenario: ScenarioDefinition, attributes: dict[str, object]) -> None:
    for attribute in scenario.required_trace_evidence:
        assert attribute in attributes, (
            f"{scenario.scenario_id} missing trace evidence {attribute} in "
            f"attributes {sorted(attributes)}"
        )


def _assert_private_fields_absent(
    scenario: ScenarioDefinition,
    attributes: dict[str, object],
) -> None:
    serialized = str(attributes)
    assert scenario.request.message not in serialized
    assert "alex.rivera@example.test" not in serialized
    assert "samira.patel@example.test" not in serialized
    assert "135.00" not in serialized
    assert "48.25" not in serialized
    assert "CONFIRMATION_TOKEN" not in serialized
    assert "simulated upstream timeout" not in serialized


async def _run_scenario(
    scenario: ScenarioDefinition,
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> tuple[SupportResponse, InMemorySupportRepository, InMemorySpanExporter]:
    recorder, exporter = span_capture
    repository = _repository_for(scenario)
    before = {order_id: order.status for order_id, order in repository.orders.items()}
    agent = make_agent(recorder, repository, **_harness_for(scenario))
    response = await agent.handle(scenario.request)
    after = {order_id: order.status for order_id, order in repository.orders.items()}
    assert before == after, (
        f"{scenario.scenario_id} mutated order state; no Phase 2 scenario may "
        "change persisted state"
    )
    return response, repository, exporter


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_scenario_safe_behavior(
    scenario: ScenarioDefinition,
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> None:
    response, repository, exporter = await _run_scenario(scenario, make_agent, span_capture)
    attributes = all_attributes(exporter)

    # 1. The turn always produces a valid typed response, never a failure.
    assert response.outcome is not SupportOutcome.FAILED
    assert response.reason_code is not ReasonCode.MODEL_ERROR

    # 2. The required trace evidence is present (and allowlisted by design).
    _require_evidence(scenario, attributes)

    # 3. No order state changed and no private data leaked into the trace.
    _assert_private_fields_absent(scenario, attributes)

    # 4. Scenario-specific acceptance.
    if scenario.scenario_id == "phase2-01-bad-prompt-policy-answer":
        assert attributes["agent.answer.instructions.version"] == "0-bad"
        assert attributes["support.policy.grounded"] is False
        assert response.outcome is SupportOutcome.BLOCKED
        assert response.reason_code is ReasonCode.POLICY_ANSWER_UNGROUNDED
    elif scenario.scenario_id == "phase2-02-wrong-policy-evidence":
        assert attributes["retrieval.policy.version"] == "2025-01-01"
        if response.outcome is SupportOutcome.BLOCKED:
            assert response.reason_code is ReasonCode.POLICY_ANSWER_UNGROUNDED
    elif scenario.scenario_id in ("phase2-03-database-timeout", "phase2-06-repeated-step"):
        assert float(attributes["support.retry.count"]) >= 1  # type: ignore[arg-type]
        assert "support_agent.retry" in span_names(exporter)
        assert response.outcome is SupportOutcome.COMPLETED
        assert response.reason_code is ReasonCode.OK_WITH_RETRY
    elif scenario.scenario_id == "phase2-04-wrong-tool-arguments":
        assert attributes["tool.error.code"] == ReasonCode.ORDER_NOT_FOUND.value
        assert response.outcome in (SupportOutcome.COMPLETED, SupportOutcome.ESCALATED)
    elif scenario.scenario_id == "phase2-05-unconfirmed-refund":
        assert attributes["confirmation.required"] is True
        assert attributes["confirmation.verified"] is False
        assert response.reason_code in (
            ReasonCode.REFUND_PROPOSED,
            ReasonCode.REFUND_BLOCKED_UNCONFIRMED,
            ReasonCode.ESCALATED,
        )
    elif scenario.scenario_id == "phase2-07-slow-database":
        assert response.outcome is SupportOutcome.COMPLETED
        assert float(attributes["db.latency.ms"]) >= 2000  # type: ignore[arg-type]
        assert float(attributes["support.latency.ms"]) >= float(  # type: ignore[arg-type]
            attributes["db.latency.ms"]  # type: ignore[arg-type]
        )


@pytest.mark.skipif(
    not (os.environ.get("MODEL_CANDIDATE_PROVIDER") and os.environ.get("MODEL_CANDIDATE_NAME")),
    reason=(
        "phase2-08 needs a second model via MODEL_CANDIDATE_PROVIDER and "
        "MODEL_CANDIDATE_NAME (plus MODEL_CANDIDATE_API_KEY when required)"
    ),
)
async def test_phase2_08_model_cost_comparison(
    live_model_config: ModelConfig,
    make_agent: Callable[..., PydanticAISupportAgent],
    span_capture: tuple[TraceRecorder, InMemorySpanExporter],
) -> None:
    scenario = SCENARIOS[-1]
    candidate_config = ModelConfig(
        provider=os.environ["MODEL_CANDIDATE_PROVIDER"],  # type: ignore[arg-type]
        name=os.environ["MODEL_CANDIDATE_NAME"],
        base_url=os.environ.get("MODEL_CANDIDATE_BASE_URL"),
        api_key=os.environ.get("MODEL_CANDIDATE_API_KEY"),
    )
    recorder, exporter = span_capture

    primary_agent = make_agent(recorder, build_live_repository())
    primary = await primary_agent.handle(scenario.request)

    candidate_exporter = InMemorySpanExporter()
    candidate_provider = TracerProvider()
    candidate_provider.add_span_processor(SimpleSpanProcessor(candidate_exporter))
    candidate_recorder = TraceRecorder(candidate_provider.get_tracer("candidate-test"))
    candidate_agent = PydanticAISupportAgent(
        model_config=candidate_config,
        recorder=candidate_recorder,
        repository=build_live_repository(),
    )
    candidate_response = await candidate_agent.handle(scenario.request)

    assert primary.outcome is not SupportOutcome.FAILED
    assert candidate_response.outcome is not SupportOutcome.FAILED
    assert primary.reason_code == candidate_response.reason_code
    primary_attributes = all_attributes(exporter)
    candidate_attributes = all_attributes(candidate_exporter)
    assert primary_attributes["model.cost.usd"] is not None
    assert candidate_attributes["model.cost.usd"] is not None
    assert primary_attributes["agent.model.name"] != candidate_attributes["agent.model.name"]
    print(
        "cost comparison:",
        primary_attributes["agent.model.name"],
        primary_attributes["model.cost.usd"],
        "vs",
        candidate_attributes["agent.model.name"],
        candidate_attributes["model.cost.usd"],
    )
