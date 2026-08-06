"""This module defines the versioned vendor-neutral SimulationScenario schema.

A scenario declares the request, approved workflow context, initial business
state, eligible actions, expected behavior, budgets, and required dependency
coverage. Expected behavior is separate from the original production output:
a failed production trace must never become the accepted expectation by
default. A scenario may reference one production trace or be designed from
fixed local data.
"""

import json
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.agent.schemas import ReasonCode, SupportOutcome, SupportRequest
from app.domain.support.schemas import OrderRead, PolicyDocumentRead, TicketRead

SIMULATION_SCENARIO_SCHEMA_VERSION = "1.0.0"


class SimulationCategory(StrEnum):
    """This enum defines the stable failure category of one scenario."""

    ANSWER_FAILURE = "answer_failure"
    RETRIEVAL_FAILURE = "retrieval_failure"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    TOOL_FAILURE = "tool_failure"
    POLICY_FAILURE = "policy_failure"
    INEFFICIENCY = "inefficiency"
    LATENCY_FAILURE = "latency_failure"
    COST_COMPARISON = "cost_comparison"


class SimulationState(BaseModel):
    """This class stores the approved disposable business state of one scenario.

    The lab loads this state into an isolated PostgreSQL sandbox. Fast unit
    tests can copy it into an in-memory adapter. It must never be loaded into
    a shared development or production database.
    """

    model_config = ConfigDict(extra="forbid")

    orders: tuple[OrderRead, ...] = ()
    tickets: tuple[TicketRead, ...] = ()
    policies: tuple[PolicyDocumentRead, ...] = ()


class WorkflowContext(BaseModel):
    """This class stores the approved workflow configuration of one scenario."""

    model_config = ConfigDict(extra="forbid")

    workflow: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=100)
    workflow_version: str = Field(min_length=1, max_length=50)
    environment: str = Field(default="local", max_length=100)
    routing_instructions_version: str | None = Field(default=None, max_length=50)
    answer_instructions_version: str | None = Field(default=None, max_length=50)
    model_provider: str | None = Field(default=None, max_length=100)
    model_name: str | None = Field(default=None, max_length=200)


class SimulationBudgets(BaseModel):
    """This class stores the explicit performance budgets of one scenario."""

    model_config = ConfigDict(extra="forbid")

    performance_budget_ms: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, ge=0)


class ExpectedStateTransition(BaseModel):
    """This class declares one accepted business-state transition."""

    model_config = ConfigDict(extra="forbid")

    resource: str = Field(pattern=r"^(order|ticket)$")
    resource_id: UUID
    from_status: str | None = Field(default=None, max_length=50)
    to_status: str = Field(min_length=1, max_length=50)
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class ExpectedBehavior(BaseModel):
    """This class stores the behavior that the lab accepts for one scenario.

    A person approves these values. A failed production output never becomes
    the expected behavior by default.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: SupportOutcome
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1)
    policy_grounded: bool | None = None
    state_transitions: tuple[ExpectedStateTransition, ...] = ()
    budgets: SimulationBudgets = Field(default_factory=SimulationBudgets)
    note: str | None = Field(default=None, max_length=1000)


class OriginalProductionBehavior(BaseModel):
    """This class stores what production actually did for one scenario.

    The original output is evidence, not an expectation. The two fields stay
    separate so a later reviewer can approve a corrected expectation.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: SupportOutcome
    reason_code: ReasonCode | None = None
    source: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class DependencyCoverageRequirement(BaseModel):
    """This class declares one dependency that a scenario needs to run safely."""

    model_config = ConfigDict(extra="forbid")

    dependency: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=100)
    kind: str = Field(pattern=r"^(recorded|stateful|either)$", default="either")
    tools: tuple[str, ...] = ()


class ScenarioEvidenceRef(BaseModel):
    """This class links one scenario to the production trace it reproduces."""

    model_config = ConfigDict(extra="forbid")

    platform: str = Field(min_length=1, max_length=50)
    project: str | None = Field(default=None, max_length=200)
    trace_id: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2000)


class SimulationScenario(BaseModel):
    """This class stores one versioned simulation scenario.

    Every scenario declares the request, approved workflow context, initial
    state, eligible actions, expected behavior, budgets, and required
    dependency coverage. ``evidence_ref`` is present only when the scenario
    reproduces one selected production trace.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=SIMULATION_SCENARIO_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    scenario_id: str = Field(pattern=r"^phase2-\d{2}-[a-z0-9-]+$")
    title: str = Field(min_length=1, max_length=300)
    category: SimulationCategory
    request: SupportRequest
    workflow_context: WorkflowContext
    initial_state: SimulationState
    eligible_actions: tuple[str, ...]
    expected_behavior: ExpectedBehavior
    original_production_behavior: OriginalProductionBehavior | None = None
    required_dependency_coverage: tuple[DependencyCoverageRequirement, ...] = ()
    evidence_ref: ScenarioEvidenceRef | None = None
    local_only_fields: tuple[str, ...] = ()
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def ensure_content_hash(self) -> "SimulationScenario":
        """This method stores the stable content hash of the scenario."""
        if self.content_hash is None:
            self.content_hash = compute_scenario_hash(self)
        return self

    @model_validator(mode="after")
    def validate_requirements_and_actions(self) -> "SimulationScenario":
        """This method rejects duplicate actions and duplicate requirements."""
        if len(set(self.eligible_actions)) != len(self.eligible_actions):
            raise ValueError("eligible_actions must not repeat a tool")
        dependencies = [requirement.dependency for requirement in self.required_dependency_coverage]
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("required_dependency_coverage must not repeat a dependency")
        return self


def compute_scenario_hash(scenario: SimulationScenario) -> str:
    """This function returns a stable hash for one scenario.

    The hash excludes the stored hash itself. Any content change changes the
    hash, so a changed scenario is a new version.
    """
    canonical = json.dumps(
        scenario.model_dump(mode="json", exclude={"content_hash"}),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


def link_evidence(
    scenario: SimulationScenario,
    *,
    platform: str,
    trace_id: str,
    project: str | None = None,
    url: str | None = None,
) -> SimulationScenario:
    """This function links one scenario to a production trace.

    The scenario keeps its own expected behavior; linking only adds the
    provenance reference to the source trace.
    """
    updated = scenario.model_copy(
        update={
            "evidence_ref": ScenarioEvidenceRef(
                platform=platform,
                project=project,
                trace_id=trace_id,
                url=url,
            ),
            "content_hash": None,
        }
    )
    updated.content_hash = compute_scenario_hash(updated)
    return updated
