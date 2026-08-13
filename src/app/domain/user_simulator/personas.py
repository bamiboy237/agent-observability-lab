"""The fixed user persona catalog: eight support and seven reference cases."""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.agent.scenarios import SCENARIOS
from app.domain.reference.workflows.six_reference import ALL_WORKFLOWS


class PersonaDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona_id: str = Field(min_length=1, pattern=r"^[a-z0-9_-]+$")
    kind: str = Field(pattern=r"^(support|reference)$")
    scenario_or_workflow_id: str = Field(min_length=1)
    persona: str = Field(min_length=1, max_length=2000)
    script: str = Field(min_length=1, max_length=4000)
    goal: str = Field(min_length=1, max_length=1000)


SUPPORT_PERSONAS = tuple(
    PersonaDefinition(
        persona_id=s.scenario_id,
        kind="support",
        scenario_or_workflow_id=s.scenario_id,
        persona=(
            "A real customer who is concise, emotional when appropriate, and does not know "
            "internal rules."
        ),
        script=s.request.message,
        goal=s.expected_safe_behavior,
    )
    for s in SCENARIOS
)
REFERENCE_PERSONAS = tuple(
    PersonaDefinition(
        persona_id=f"reference-{w.workflow_id}",
        kind="reference",
        scenario_or_workflow_id=w.workflow_id,
        persona="A business user describing a time-sensitive request in ordinary language.",
        script=f"Please help with the {w.name.lower()} case.",
        goal=w.expectation.outcome,
    )
    for w in ALL_WORKFLOWS
)
ALL_PERSONAS = SUPPORT_PERSONAS + REFERENCE_PERSONAS
assert len(SUPPORT_PERSONAS) == 8
assert len(REFERENCE_PERSONAS) == 7
PERSONA_BY_ID = {p.persona_id: p for p in ALL_PERSONAS}
