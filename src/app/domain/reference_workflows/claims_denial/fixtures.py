"""Deterministic offline fixture data for the healthcare claim denial workflow.

This module is self-contained on purpose: it imports only the standard
library and pydantic. It mirrors the shape of the lab evidence, scenario,
and bundle contracts (see DESIGN.md) without importing lab modules, so the
data can be loaded and validated in any offline environment.

Every identifier is a stable UUID derived from the workflow namespace, so
repeated imports produce identical data and hashes.
"""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

WORKFLOW = "claims_denial_agent"
WORKFLOW_VERSION = "1.2.0"
MODEL_PROVIDER = "openai"
MODEL_NAME = "gpt-5.2"
NAMESPACE = UUID("c3e9a047-5d2b-4c8e-8a6d-7b4f9e2c3d05")


def seed_id(name: str) -> UUID:
    """Return the stable UUID for one named fixture record."""
    return uuid5(NAMESPACE, name)


# --------------------------------------------------------------------------
# Stateful system
# --------------------------------------------------------------------------


class ClaimStatus(StrEnum):
    SUBMITTED = "submitted"
    DENIED = "denied"
    IN_REVIEW = "in_review"
    APPEALED = "appealed"
    PAID = "paid"


class AppealStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Payer(BaseModel):
    """One health plan whose policies govern claim decisions."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str


class Claim(BaseModel):
    """One denied claim with its payer denial reason. EOB text is local-only."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    payer_id: UUID
    procedure_code: str
    diagnosis_code: str
    status: ClaimStatus
    denial_code: str | None = None
    denial_reason: str = ""
    amount: str
    eob_text: str = ""


class Policy(BaseModel):
    """One versioned payer medical policy the appeal must cite."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    payer_id: UUID
    slug: str
    version: str
    title: str
    criteria: tuple[str, ...]
    content: str
    content_hash: str


class ClinicalNote(BaseModel):
    """One clinical note for the claim. Note text is local-only."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    claim_id: UUID
    content: str


class Appeal(BaseModel):
    """One appeal with a policy-grounded success score."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    claim_id: UUID
    status: AppealStatus
    success_score: float = Field(ge=0.0, le=1.0)
    policy_version: str | None = None
    missing_evidence: tuple[str, ...] = ()


class ClaimsState(BaseModel):
    """The disposable business state one scenario starts from."""

    model_config = ConfigDict(extra="forbid")

    payers: tuple[Payer, ...] = ()
    claims: tuple[Claim, ...] = ()
    policies: tuple[Policy, ...] = ()
    clinical_notes: tuple[ClinicalNote, ...] = ()
    appeals: tuple[Appeal, ...] = ()


# --------------------------------------------------------------------------
# Tools: safe vs sensitive
# --------------------------------------------------------------------------


class Tool(BaseModel):
    """One tool with its sensitivity class and confirmation gate."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    sensitivity: Literal["safe", "sensitive"]
    requires_confirmation: bool = False


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="get_claim",
        description="Read one claim with its payer denial reason.",
        sensitivity="safe",
    ),
    Tool(
        name="retrieve_policy",
        description="Retrieve the payer medical policy for one procedure (retrieval).",
        sensitivity="safe",
    ),
    Tool(
        name="get_clinical_notes",
        description="Read the clinical notes attached to one claim.",
        sensitivity="safe",
    ),
    Tool(
        name="search_prior_appeals",
        description="Search prior appeals for the same payer and procedure.",
        sensitivity="safe",
    ),
    Tool(
        name="save_appeal_draft",
        description="Save a policy-cited appeal draft for human review.",
        sensitivity="sensitive",
        requires_confirmation=False,
    ),
    Tool(
        name="submit_appeal",
        description="Submit the appeal to the payer (external effect).",
        sensitivity="sensitive",
        requires_confirmation=True,
    ),
    Tool(
        name="request_missing_evidence",
        description="Contact the provider office for missing clinical evidence.",
        sensitivity="sensitive",
        requires_confirmation=True,
    ),
    Tool(
        name="escalate_to_reviewer",
        description="Escalate the claim to a human revenue-cycle reviewer.",
        sensitivity="sensitive",
        requires_confirmation=False,
    ),
)

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
SAFE_TOOLS = tuple(tool.name for tool in TOOLS if tool.sensitivity == "safe")
SENSITIVE_TOOLS = tuple(tool.name for tool in TOOLS if tool.sensitivity == "sensitive")


# --------------------------------------------------------------------------
# Scenario-shaped fixtures (mirror the lab SimulationScenario contract)
# --------------------------------------------------------------------------


class ClaimsRequest(BaseModel):
    """One denial-management turn. The EOB denial text is local-only."""

    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
    trigger: str = Field(min_length=1, max_length=200)


class WorkflowContext(BaseModel):
    """The approved workflow configuration of one scenario."""

    model_config = ConfigDict(extra="forbid")

    workflow: str
    workflow_version: str
    environment: str = "local"
    routing_instructions_version: str | None = None
    answer_instructions_version: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    autonomy_level: str | None = None


class ExpectedStateTransition(BaseModel):
    """One accepted business-state transition for this workflow."""

    model_config = ConfigDict(extra="forbid")

    resource: Literal["claim", "appeal", "policy"]
    resource_id: UUID | None = None
    any_resource_id: bool = False
    from_status: str | None = None
    to_status: str
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class ExpectedBehavior(BaseModel):
    """The behavior a person approved for one scenario."""

    model_config = ConfigDict(extra="forbid")

    outcome: str
    reason_codes: tuple[str, ...] = Field(min_length=1)
    policy_grounded: bool | None = None
    policy_version: str | None = None
    permitted_state_transitions: tuple[ExpectedStateTransition, ...] = ()
    budgets: dict[str, int | float | None] = {}
    note: str | None = None


class OriginalProductionBehavior(BaseModel):
    """What production actually did. Evidence, not an expectation."""

    model_config = ConfigDict(extra="forbid")

    outcome: str
    reason_code: str | None = None
    source: str | None = None
    note: str | None = None


class DependencyCoverage(BaseModel):
    """One dependency a scenario needs to run safely."""

    model_config = ConfigDict(extra="forbid")

    dependency: str
    kind: Literal["recorded", "stateful", "either"]
    tools: tuple[str, ...] = ()


class DependencyCall(BaseModel):
    """One recorded dependency call, mirroring TraceEvidence.DependencyCall."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    error_code: str | None = None
    duration_ms: float | None = None


class PolicyDecision(BaseModel):
    """One recorded policy decision, mirroring TraceEvidence.PolicyDecision."""

    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    decision: str | None = None
    reason_code: str | None = None


class Confirmation(BaseModel):
    """The confirmation outcome, mirroring TraceEvidence.ConfirmationDecision."""

    model_config = ConfigDict(extra="forbid")

    required: bool
    verified: bool


class TraceFacts(BaseModel):
    """A compact projection of the lab TraceEvidence shape for one run."""

    model_config = ConfigDict(extra="forbid")

    source_platform: str
    trace_id: str
    outcome: str
    reason_code: str
    dependency_calls: tuple[DependencyCall, ...] = ()
    policy_decisions: tuple[PolicyDecision, ...] = ()
    confirmation: Confirmation | None = None
    retry_count: int = 0
    total_latency_ms: float
    model_latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ComparisonVariable(BaseModel):
    """The one baseline/candidate variable this workflow compares."""

    model_config = ConfigDict(extra="forbid")

    name: str
    baseline: str
    candidate: str
    unit: str
    measure: str


class Scenario(BaseModel):
    """One scenario in the lab SimulationScenario shape, workflow-local."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    scenario_id: str
    title: str
    category: str
    request: ClaimsRequest
    workflow_context: WorkflowContext
    initial_state: ClaimsState
    eligible_actions: tuple[str, ...]
    expected_behavior: ExpectedBehavior
    original_production_behavior: OriginalProductionBehavior | None = None
    required_dependency_coverage: tuple[DependencyCoverage, ...] = ()
    evidence: TraceFacts | None = None
    local_only_fields: tuple[str, ...] = ()
    comparison: ComparisonVariable | None = None
    content_hash: str | None = None


def compute_content_hash(scenario: Scenario) -> str:
    """Return the stable content hash of one scenario."""
    canonical = json.dumps(
        scenario.model_dump(mode="json", exclude={"content_hash"}),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


# --------------------------------------------------------------------------
# Deterministic records
# --------------------------------------------------------------------------

MERIDIAN_PAYER = Payer(
    id=seed_id("payer:meridian-health"),
    name="Meridian Health Plan",
)

CURRENT_POLICY = Policy(
    id=seed_id("policy:meridian-ct-scan:2026-06-01"),
    payer_id=MERIDIAN_PAYER.id,
    slug="ct-scan-with-contrast",
    version="2026-06-01",
    title="CT Scan with Contrast Medical Policy",
    criteria=(
        "documented clinical indication for the scan",
        "prior imaging result or symptom record in the chart",
        "contrast allergy screening documented",
    ),
    content=(
        "# CT Scan with Contrast Medical Policy\n\n"
        "Policy version: 2026-06-01\n\n"
        "Coverage requires all three criteria: a documented clinical "
        "indication, a prior imaging result or symptom record, and a "
        "documented contrast allergy screening. Appeals must cite the "
        "policy version and the chart evidence for each criterion.\n"
    ),
    content_hash=sha256(
        (
            "# CT Scan with Contrast Medical Policy\n\n"
            "Policy version: 2026-06-01\n\n"
            "Coverage requires all three criteria: a documented clinical "
            "indication, a prior imaging result or symptom record, and a "
            "documented contrast allergy screening. Appeals must cite the "
            "policy version and the chart evidence for each criterion.\n"
        ).encode()
    ).hexdigest(),
)

STALE_POLICY = Policy(
    id=seed_id("policy:meridian-ct-scan:2025-01-01"),
    payer_id=MERIDIAN_PAYER.id,
    slug="ct-scan-with-contrast",
    version="2025-01-01",
    title="CT Scan with Contrast Medical Policy",
    criteria=("documented clinical indication for the scan",),
    content=(
        "# CT Scan with Contrast Medical Policy\n\n"
        "Policy version: 2025-01-01\n\n"
        "Coverage requires one documented clinical indication. Appeals must "
        "cite the policy version and the chart evidence.\n"
    ),
    content_hash=sha256(
        (
            "# CT Scan with Contrast Medical Policy\n\n"
            "Policy version: 2025-01-01\n\n"
            "Coverage requires one documented clinical indication. Appeals must "
            "cite the policy version and the chart evidence.\n"
        ).encode()
    ).hexdigest(),
)

CLAIM_7712 = Claim(
    id=seed_id("claim:7712"),
    payer_id=MERIDIAN_PAYER.id,
    procedure_code="74177",
    diagnosis_code="R10.9",
    status=ClaimStatus.DENIED,
    denial_code="CO-197",
    denial_reason="Preauthorization review: clinical criteria not met.",
    amount="1840.00",
    eob_text=(
        "Denial CO-197: the service was denied because the submitted record "
        "did not document all medical policy criteria. You may appeal with "
        "additional documentation within 180 days."
    ),
)

CLAIM_7713 = Claim(
    id=seed_id("claim:7713"),
    payer_id=MERIDIAN_PAYER.id,
    procedure_code="74177",
    diagnosis_code="R10.9",
    status=ClaimStatus.DENIED,
    denial_code="CO-197",
    denial_reason="Preauthorization review: clinical criteria not met.",
    amount="1840.00",
    eob_text=(
        "Denial CO-197: the submitted record did not document all medical "
        "policy criteria. You may appeal with additional documentation."
    ),
)

NOTES_7712 = ClinicalNote(
    id=seed_id("note:7712"),
    claim_id=CLAIM_7712.id,
    content=(
        "Patient reports four weeks of right-lower-quadrant pain. Prior "
        "ultrasound from March shows no acute findings. Contrast allergy "
        "screening documented: no known allergies. CT abdomen with contrast "
        "ordered to evaluate persistent pain."
    ),
)

NOTES_7713 = ClinicalNote(
    id=seed_id("note:7713"),
    claim_id=CLAIM_7713.id,
    content=(
        "Patient reports intermittent abdominal pain. No prior imaging on "
        "file. Contrast allergy screening not documented. CT abdomen with "
        "contrast ordered."
    ),
)

EVIDENCE_TRACE_IDS: tuple[str, ...] = (
    "ref-claims-01-stale-policy",
    "ref-claims-02-auto-submit-threshold",
    "ref-claims-03-policy-timeout",
)

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        scenario_id="ref-claims-01-stale-policy",
        title="Policy retrieval serves the stale payer policy",
        category="retrieval_failure",
        request=ClaimsRequest(
            claim_id=CLAIM_7712.id,
            trigger="denial_received: claim 7712 denied CO-197",
        ),
        workflow_context=WorkflowContext(
            workflow=WORKFLOW,
            workflow_version=WORKFLOW_VERSION,
            routing_instructions_version="1",
            answer_instructions_version="1",
            model_provider=MODEL_PROVIDER,
            model_name=MODEL_NAME,
            autonomy_level="human_confirm",
        ),
        initial_state=ClaimsState(
            payers=(MERIDIAN_PAYER,),
            claims=(CLAIM_7712,),
            policies=(STALE_POLICY,),
            clinical_notes=(NOTES_7712,),
            appeals=(),
        ),
        eligible_actions=tuple(tool.name for tool in TOOLS),
        expected_behavior=ExpectedBehavior(
            outcome="blocked",
            reason_codes=("policy_answer_ungrounded", "escalated_to_reviewer"),
            policy_grounded=False,
            policy_version="2025-01-01",
            permitted_state_transitions=(
                ExpectedStateTransition(
                    resource="claim",
                    resource_id=CLAIM_7712.id,
                    from_status="denied",
                    to_status="in_review",
                    reason_code="escalated_to_reviewer",
                ),
            ),
            budgets={"performance_budget_ms": 10000},
            note=(
                "The policy store serves only the stale 2025-01-01 version, "
                "which omits the contrast-allergy criterion. The agent must "
                "not draft or submit an appeal citing stale criteria; it "
                "records retrieval.policy.version=2025-01-01 and grounded="
                "false, and escalates the claim to a human reviewer. No "
                "appeal may be created or submitted."
            ),
        ),
        original_production_behavior=OriginalProductionBehavior(
            outcome="completed",
            reason_code="appeal_submitted",
            source="fixture:langsmith",
            note=(
                "Production cited the stale one-criterion policy and submitted "
                "an appeal that the payer rejected for missing the contrast "
                "allergy screening."
            ),
        ),
        required_dependency_coverage=(
            DependencyCoverage(
                dependency="claims.database",
                kind="stateful",
                tools=("get_claim", "get_clinical_notes", "escalate_to_reviewer"),
            ),
            DependencyCoverage(
                dependency="policy.retrieval",
                kind="recorded",
                tools=("retrieve_policy",),
            ),
            DependencyCoverage(
                dependency="appeal.submission",
                kind="recorded",
                tools=("submit_appeal",),
            ),
        ),
        evidence=TraceFacts(
            source_platform="langsmith",
            trace_id="ref-claims-01-stale-policy",
            outcome="blocked",
            reason_code="policy_answer_ungrounded",
            dependency_calls=(
                DependencyCall(kind="database", name="get_claim", duration_ms=18.0),
                DependencyCall(kind="retrieval", name="retrieve_policy", duration_ms=140.0),
                DependencyCall(kind="escalation", name="escalate_to_reviewer", duration_ms=55.0),
            ),
            policy_decisions=(
                PolicyDecision(
                    version="2025-01-01",
                    decision="insufficient",
                    reason_code="policy_answer_ungrounded",
                ),
            ),
            retry_count=0,
            total_latency_ms=4200.0,
            model_latency_ms=2400.0,
            input_tokens=2900,
            output_tokens=520,
            cost_usd=0.016,
        ),
        local_only_fields=("EOB denial text", "clinical note content", "policy content"),
    ),
    Scenario(
        scenario_id="ref-claims-02-auto-submit-threshold",
        title="Auto-submit threshold and confirmation gate block a weak appeal",
        category="policy_failure",
        request=ClaimsRequest(
            claim_id=CLAIM_7713.id,
            trigger="denial_received: claim 7713 denied CO-197",
        ),
        workflow_context=WorkflowContext(
            workflow=WORKFLOW,
            workflow_version=WORKFLOW_VERSION,
            routing_instructions_version="1",
            answer_instructions_version="1",
            model_provider=MODEL_PROVIDER,
            model_name=MODEL_NAME,
            autonomy_level="auto_threshold_0.8",
        ),
        initial_state=ClaimsState(
            payers=(MERIDIAN_PAYER,),
            claims=(CLAIM_7713,),
            policies=(CURRENT_POLICY,),
            clinical_notes=(NOTES_7713,),
            appeals=(),
        ),
        eligible_actions=tuple(tool.name for tool in TOOLS),
        expected_behavior=ExpectedBehavior(
            outcome="blocked",
            reason_codes=("appeal_blocked_below_threshold", "confirmation_required"),
            policy_grounded=True,
            policy_version="2026-06-01",
            permitted_state_transitions=(
                ExpectedStateTransition(
                    resource="appeal",
                    resource_id=seed_id("appeal:draft:7713"),
                    from_status=None,
                    to_status="draft",
                    reason_code="appeal_drafted",
                ),
            ),
            budgets={"performance_budget_ms": 10000},
            note=(
                "Gap analysis finds two missing criteria (prior imaging, "
                "contrast allergy screening), so the success score is 0.72, "
                "below the 0.8 auto-submit threshold. The agent may save a "
                "draft and request evidence, but submit_appeal fails: "
                "confirmation.required=true and confirmation.verified=false. "
                "The claim stays denied; no appeal is submitted."
            ),
        ),
        original_production_behavior=OriginalProductionBehavior(
            outcome="blocked",
            reason_code="appeal_blocked_below_threshold",
            source="fixture:langsmith",
            note="Production blocked the same submission at the threshold gate.",
        ),
        required_dependency_coverage=(
            DependencyCoverage(
                dependency="claims.database",
                kind="stateful",
                tools=("get_claim", "get_clinical_notes", "save_appeal_draft"),
            ),
            DependencyCoverage(
                dependency="policy.retrieval",
                kind="recorded",
                tools=("retrieve_policy",),
            ),
            DependencyCoverage(
                dependency="appeal.submission",
                kind="recorded",
                tools=("submit_appeal",),
            ),
        ),
        evidence=TraceFacts(
            source_platform="langsmith",
            trace_id="ref-claims-02-auto-submit-threshold",
            outcome="blocked",
            reason_code="appeal_blocked_below_threshold",
            dependency_calls=(
                DependencyCall(kind="database", name="get_claim", duration_ms=16.0),
                DependencyCall(kind="retrieval", name="retrieve_policy", duration_ms=95.0),
                DependencyCall(kind="database", name="save_appeal_draft", duration_ms=40.0),
                DependencyCall(
                    kind="tool",
                    name="submit_appeal",
                    error_code="confirmation_required",
                    duration_ms=12.0,
                ),
            ),
            policy_decisions=(
                PolicyDecision(
                    version="2026-06-01",
                    decision="score_0.72_below_0.8",
                    reason_code="appeal_blocked_below_threshold",
                ),
            ),
            confirmation=Confirmation(required=True, verified=False),
            retry_count=0,
            total_latency_ms=3800.0,
            model_latency_ms=2000.0,
            input_tokens=3100,
            output_tokens=470,
            cost_usd=0.017,
        ),
        local_only_fields=("EOB denial text", "clinical note content", "policy content"),
        comparison=ComparisonVariable(
            name="appeal_autonomy_level",
            baseline="human_confirm",
            candidate="auto_threshold_0.8",
            unit="appeals submitted without human review",
            measure=(
                "Run the same claim under both workflow configurations. The "
                "baseline requires a human confirmation before every "
                "submit_appeal. The candidate auto-submits when the "
                "policy-grounded success score is at least 0.8. This scenario "
                "is the boundary case: score 0.72 must block under both "
                "variants. Compare submitted appeals, blocked appeals, "
                "escalations, and resolution latency."
            ),
        ),
    ),
    Scenario(
        scenario_id="ref-claims-03-policy-timeout",
        title="Policy retrieval times out once then succeeds",
        category="infrastructure_failure",
        request=ClaimsRequest(
            claim_id=CLAIM_7712.id,
            trigger="denial_received: claim 7712 denied CO-197",
        ),
        workflow_context=WorkflowContext(
            workflow=WORKFLOW,
            workflow_version=WORKFLOW_VERSION,
            routing_instructions_version="1",
            answer_instructions_version="1",
            model_provider=MODEL_PROVIDER,
            model_name=MODEL_NAME,
            autonomy_level="human_confirm",
        ),
        initial_state=ClaimsState(
            payers=(MERIDIAN_PAYER,),
            claims=(CLAIM_7712,),
            policies=(CURRENT_POLICY,),
            clinical_notes=(NOTES_7712,),
            appeals=(),
        ),
        eligible_actions=tuple(tool.name for tool in TOOLS),
        expected_behavior=ExpectedBehavior(
            outcome="completed",
            reason_codes=("ok_with_retry", "appeal_drafted"),
            policy_grounded=True,
            policy_version="2026-06-01",
            permitted_state_transitions=(
                ExpectedStateTransition(
                    resource="appeal",
                    resource_id=seed_id("appeal:draft:7712"),
                    from_status=None,
                    to_status="draft",
                    reason_code="appeal_drafted",
                ),
            ),
            budgets={"performance_budget_ms": 12000},
            note=(
                "The first retrieve_policy call fails with timeout; the retry "
                "succeeds. The agent grounds the appeal in the current "
                "2026-06-01 policy, scores it above threshold, and saves a "
                "draft. The trace records the retry span and "
                "tool.error.code=timeout. The draft is not submitted: "
                "confirmation is still required."
            ),
        ),
        original_production_behavior=OriginalProductionBehavior(
            outcome="completed",
            reason_code="ok_with_retry",
            source="fixture:langsmith",
            note="The policy service raised TimeoutError once before success.",
        ),
        required_dependency_coverage=(
            DependencyCoverage(
                dependency="claims.database",
                kind="stateful",
                tools=("get_claim", "get_clinical_notes", "save_appeal_draft"),
            ),
            DependencyCoverage(
                dependency="policy.retrieval",
                kind="recorded",
                tools=("retrieve_policy",),
            ),
        ),
        evidence=TraceFacts(
            source_platform="langsmith",
            trace_id="ref-claims-03-policy-timeout",
            outcome="completed",
            reason_code="ok_with_retry",
            dependency_calls=(
                DependencyCall(kind="database", name="get_claim", duration_ms=14.0),
                DependencyCall(
                    kind="retrieval",
                    name="retrieve_policy",
                    error_code="timeout",
                    duration_ms=3000.0,
                ),
                DependencyCall(kind="retrieval", name="retrieve_policy", duration_ms=88.0),
                DependencyCall(kind="database", name="save_appeal_draft", duration_ms=38.0),
            ),
            policy_decisions=(
                PolicyDecision(
                    version="2026-06-01",
                    decision="score_0.85_above_0.8",
                    reason_code="appeal_grounded",
                ),
            ),
            retry_count=1,
            total_latency_ms=6900.0,
            model_latency_ms=2600.0,
            input_tokens=3400,
            output_tokens=610,
            cost_usd=0.019,
        ),
        local_only_fields=("EOB denial text", "clinical note content", "policy content"),
    ),
)

for _scenario in SCENARIOS:
    _scenario.content_hash = compute_content_hash(_scenario)
