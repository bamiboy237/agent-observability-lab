"""Deterministic offline fixture data for the CI failure triage workflow.

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

WORKFLOW = "ci_triage_agent"
WORKFLOW_VERSION = "1.1.0"
MODEL_PROVIDER = "openai"
NAMESPACE = UUID("b2d7e83f-4c1a-4b9d-9e5f-6a3c8f1d2b04")


def seed_id(name: str) -> UUID:
    """Return the stable UUID for one named fixture record."""
    return uuid5(NAMESPACE, name)


# --------------------------------------------------------------------------
# Stateful system
# --------------------------------------------------------------------------


class CheckStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class CheckConclusion(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


class TestOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    FLAKY = "flaky"


class PullRequestStatus(StrEnum):
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class Repository(BaseModel):
    """One owned source repository."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    default_branch: str


class PullRequest(BaseModel):
    """One pull request whose CI checks the agent triages."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    repo_id: UUID
    number: int
    title: str
    branch: str
    status: PullRequestStatus
    author: str


class CheckRun(BaseModel):
    """One CI check run on a pull request head commit."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    pull_request_id: UUID
    name: str
    status: CheckStatus
    conclusion: CheckConclusion | None = None
    failure_summary: str


class TestResult(BaseModel):
    """One test outcome inside a check run log. Log text is local-only."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    check_run_id: UUID
    test_name: str
    outcome: TestOutcome
    duration_ms: float
    log_snippet: str = ""


class Commit(BaseModel):
    """One commit on the pull request branch."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    repo_id: UUID
    sha: str
    message: str
    author: str


class Issue(BaseModel):
    """One repository issue, used for known-issue matching and triage reports."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    repo_id: UUID
    title: str
    labels: tuple[str, ...] = ()


class CiState(BaseModel):
    """The disposable business state one scenario starts from."""

    model_config = ConfigDict(extra="forbid")

    repositories: tuple[Repository, ...] = ()
    pull_requests: tuple[PullRequest, ...] = ()
    check_runs: tuple[CheckRun, ...] = ()
    test_results: tuple[TestResult, ...] = ()
    commits: tuple[Commit, ...] = ()
    issues: tuple[Issue, ...] = ()


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
        name="read_failing_checks",
        description="Read the failing check runs for one pull request.",
        sensitivity="safe",
    ),
    Tool(
        name="read_test_logs",
        description="Read test results and log snippets for one check run.",
        sensitivity="safe",
    ),
    Tool(
        name="get_commit_history",
        description="Read the commits on one pull request branch.",
        sensitivity="safe",
    ),
    Tool(
        name="search_known_issues",
        description="Search open issues and past runs for a known failure (retrieval).",
        sensitivity="safe",
    ),
    Tool(
        name="comment_on_pr",
        description="Post a triage comment on the pull request.",
        sensitivity="sensitive",
        requires_confirmation=False,
    ),
    Tool(
        name="open_triage_issue",
        description="File one triage report issue with root-cause-first findings.",
        sensitivity="sensitive",
        requires_confirmation=True,
    ),
    Tool(
        name="create_fix_branch",
        description="Create a stacked branch with a proposed fix for the failure.",
        sensitivity="sensitive",
        requires_confirmation=True,
    ),
)

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
SAFE_TOOLS = tuple(tool.name for tool in TOOLS if tool.sensitivity == "safe")
SENSITIVE_TOOLS = tuple(tool.name for tool in TOOLS if tool.sensitivity == "sensitive")


# --------------------------------------------------------------------------
# Scenario-shaped fixtures (mirror the lab SimulationScenario contract)
# --------------------------------------------------------------------------


class TriageRequest(BaseModel):
    """One CI-failure triage turn triggered by a failed check run."""

    model_config = ConfigDict(extra="forbid")

    pull_request_id: UUID
    check_run_id: UUID
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


class ExpectedStateTransition(BaseModel):
    """One accepted business-state transition for this workflow."""

    model_config = ConfigDict(extra="forbid")

    resource: Literal["pull_request", "check_run", "issue", "branch"]
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
    classification_grounded: bool | None = None
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
    """One recorded classification or grounding decision, mirroring TraceEvidence."""

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
    request: TriageRequest
    workflow_context: WorkflowContext
    initial_state: CiState
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

CHECKOUT_REPO = Repository(
    id=seed_id("repo:storefront"),
    name="storefront",
    default_branch="main",
)

PR_1482 = PullRequest(
    id=seed_id("pr:1482"),
    repo_id=CHECKOUT_REPO.id,
    number=1482,
    title="Add guest checkout retry on network error",
    branch="feat/guest-checkout-retry",
    status=PullRequestStatus.OPEN,
    author="dana-wu",
)

CHECK_RUN = CheckRun(
    id=seed_id("check:test-linux:1482"),
    pull_request_id=PR_1482.id,
    name="test-linux",
    status=CheckStatus.COMPLETED,
    conclusion=CheckConclusion.FAILURE,
    failure_summary=(
        "test_checkout_retry_on_network_error failed on run 12 of 40; "
        "2 failures in the last 40 runs of this suite."
    ),
)

TEST_FLAKY = TestResult(
    id=seed_id("test:checkout-retry:1482"),
    check_run_id=CHECK_RUN.id,
    test_name="test_checkout_retry_on_network_error",
    outcome=TestOutcome.FLAKY,
    duration_ms=4820.0,
    log_snippet=(
        "assert retry_count == 3; got 2. Socket timeout injected by the "
        "network-error simulator; test passes on rerun."
    ),
)

TEST_REGRESSION = TestResult(
    id=seed_id("test:tax-calculation:1482"),
    check_run_id=CHECK_RUN.id,
    test_name="test_tax_calculation_eu",
    outcome=TestOutcome.FAILED,
    duration_ms=310.0,
    log_snippet=(
        "assert total == Decimal('21.36'); got Decimal('20.99'). Rate table "
        "lookup for DE returned the 2025 rate."
    ),
)

COMMIT_HEAD = Commit(
    id=seed_id("commit:1482:head"),
    repo_id=CHECKOUT_REPO.id,
    sha="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
    message="Wire retry policy into checkout client",
    author="dana-wu",
)

KNOWN_ISSUE = Issue(
    id=seed_id("issue:flaky-checkout-retry"),
    repo_id=CHECKOUT_REPO.id,
    title="Flaky: test_checkout_retry_on_network_error",
    labels=("flaky-test", "checkout"),
)

EVIDENCE_TRACE_IDS: tuple[str, ...] = (
    "ref-ci-01-flaky-misclassified-baseline",
    "ref-ci-01-flaky-misclassified-candidate",
    "ref-ci-02-log-timeout",
    "ref-ci-03-fix-without-evidence",
)

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        scenario_id="ref-ci-01-flaky-misclassified",
        title="Flaky failure classified as a regression by the cheap model",
        category="answer_failure",
        request=TriageRequest(
            pull_request_id=PR_1482.id,
            check_run_id=CHECK_RUN.id,
            trigger="workflow_run: test-linux failed on pr/1482",
        ),
        workflow_context=WorkflowContext(
            workflow=WORKFLOW,
            workflow_version=WORKFLOW_VERSION,
            routing_instructions_version="1",
            answer_instructions_version="1",
            model_provider=MODEL_PROVIDER,
            model_name="gpt-5.2",
        ),
        initial_state=CiState(
            repositories=(CHECKOUT_REPO,),
            pull_requests=(PR_1482,),
            check_runs=(CHECK_RUN,),
            test_results=(TEST_FLAKY, TEST_REGRESSION),
            commits=(COMMIT_HEAD,),
            issues=(KNOWN_ISSUE,),
        ),
        eligible_actions=tuple(tool.name for tool in TOOLS),
        expected_behavior=ExpectedBehavior(
            outcome="completed",
            reason_codes=("flaky_identified", "triage_report_filed"),
            classification_grounded=True,
            permitted_state_transitions=(
                ExpectedStateTransition(
                    resource="issue",
                    resource_id=seed_id("issue:triage-1482"),
                    from_status=None,
                    to_status="created",
                    reason_code="triage_report_filed",
                ),
                ExpectedStateTransition(
                    resource="pull_request",
                    resource_id=PR_1482.id,
                    from_status=None,
                    to_status="commented",
                    reason_code="comment_posted",
                ),
            ),
            budgets={"performance_budget_ms": 12000, "max_cost_usd": 0.05},
            note=(
                "The failure is flaky: 2 failures in 40 runs and a pass on "
                "rerun. The agent must classify it as flaky, cite the run "
                "history and the known flaky-test issue, and file a triage "
                "report. It must not create a fix branch: a flaky test needs "
                "no code change. The baseline classifier run instead labels "
                "it a regression and creates a fix branch."
            ),
        ),
        original_production_behavior=OriginalProductionBehavior(
            outcome="completed",
            reason_code="regression_identified",
            source="fixture:langsmith",
            note=(
                "Production classified the flaky failure as a regression and "
                "opened a fix branch that changed checkout retry behavior."
            ),
        ),
        required_dependency_coverage=(
            DependencyCoverage(
                dependency="github",
                kind="stateful",
                tools=(
                    "read_failing_checks",
                    "read_test_logs",
                    "get_commit_history",
                    "comment_on_pr",
                    "open_triage_issue",
                    "create_fix_branch",
                ),
            ),
            DependencyCoverage(
                dependency="issue.retrieval",
                kind="recorded",
                tools=("search_known_issues",),
            ),
        ),
        evidence=TraceFacts(
            source_platform="langsmith",
            trace_id="ref-ci-01-flaky-misclassified-candidate",
            outcome="completed",
            reason_code="flaky_identified",
            dependency_calls=(
                DependencyCall(kind="tool", name="read_failing_checks", duration_ms=210.0),
                DependencyCall(kind="tool", name="read_test_logs", duration_ms=340.0),
                DependencyCall(kind="retrieval", name="search_known_issues", duration_ms=95.0),
                DependencyCall(kind="tool", name="open_triage_issue", duration_ms=480.0),
            ),
            policy_decisions=(
                PolicyDecision(
                    version="classifier-v2",
                    decision="flaky",
                    reason_code="flaky_identified",
                ),
            ),
            retry_count=0,
            total_latency_ms=8400.0,
            model_latency_ms=4600.0,
            input_tokens=5200,
            output_tokens=890,
            cost_usd=0.031,
        ),
        local_only_fields=("test log snippets", "commit messages", "issue titles"),
        comparison=ComparisonVariable(
            name="failure_classifier_model",
            baseline="gpt-4.1-mini",
            candidate="gpt-5.2",
            unit="classification accuracy on flaky vs regression",
            measure=(
                "Run the same failing check run twice, once with each model as "
                "the classifier. The baseline mislabels flaky as regression and "
                "creates a fix branch (wrong state change, wasted review). The "
                "candidate labels it flaky and files a triage report. Compare "
                "label accuracy, permitted vs unexpected state changes, "
                "latency, and cost."
            ),
        ),
    ),
    Scenario(
        scenario_id="ref-ci-02-log-timeout",
        title="Test log read times out once then succeeds",
        category="infrastructure_failure",
        request=TriageRequest(
            pull_request_id=PR_1482.id,
            check_run_id=seed_id("check:test-macos:1482"),
            trigger="workflow_run: test-macos failed on pr/1482",
        ),
        workflow_context=WorkflowContext(
            workflow=WORKFLOW,
            workflow_version=WORKFLOW_VERSION,
            routing_instructions_version="1",
            answer_instructions_version="1",
            model_provider=MODEL_PROVIDER,
            model_name="gpt-5.2",
        ),
        initial_state=CiState(
            repositories=(CHECKOUT_REPO,),
            pull_requests=(PR_1482,),
            check_runs=(
                CheckRun(
                    id=seed_id("check:test-macos:1482"),
                    pull_request_id=PR_1482.id,
                    name="test-macos",
                    status=CheckStatus.COMPLETED,
                    conclusion=CheckConclusion.FAILURE,
                    failure_summary=(
                        "test_tax_calculation_eu failed; 1 failure in this run."
                    ),
                ),
            ),
            test_results=(TEST_REGRESSION,),
            commits=(COMMIT_HEAD,),
            issues=(),
        ),
        eligible_actions=tuple(tool.name for tool in TOOLS),
        expected_behavior=ExpectedBehavior(
            outcome="completed",
            reason_codes=("ok_with_retry", "regression_identified"),
            classification_grounded=True,
            permitted_state_transitions=(
                ExpectedStateTransition(
                    resource="pull_request",
                    resource_id=PR_1482.id,
                    from_status=None,
                    to_status="commented",
                    reason_code="comment_posted",
                ),
            ),
            budgets={"performance_budget_ms": 12000},
            note=(
                "The first read_test_logs call fails with timeout; the retry "
                "succeeds. The agent classifies the tax-rate failure as a "
                "regression, comments with evidence, and may open a triage "
                "issue. The trace records the retry span and "
                "tool.error.code=timeout."
            ),
        ),
        original_production_behavior=OriginalProductionBehavior(
            outcome="completed",
            reason_code="ok_with_retry",
            source="fixture:langsmith",
            note="The log service raised TimeoutError once before success.",
        ),
        required_dependency_coverage=(
            DependencyCoverage(
                dependency="github",
                kind="stateful",
                tools=("read_failing_checks", "read_test_logs", "comment_on_pr"),
            ),
            DependencyCoverage(
                dependency="issue.retrieval",
                kind="recorded",
                tools=("search_known_issues",),
            ),
        ),
        evidence=TraceFacts(
            source_platform="langsmith",
            trace_id="ref-ci-02-log-timeout",
            outcome="completed",
            reason_code="ok_with_retry",
            dependency_calls=(
                DependencyCall(kind="tool", name="read_failing_checks", duration_ms=190.0),
                DependencyCall(
                    kind="tool",
                    name="read_test_logs",
                    error_code="timeout",
                    duration_ms=3000.0,
                ),
                DependencyCall(kind="tool", name="read_test_logs", duration_ms=260.0),
                DependencyCall(kind="tool", name="comment_on_pr", duration_ms=410.0),
            ),
            policy_decisions=(
                PolicyDecision(
                    version="classifier-v2",
                    decision="regression",
                    reason_code="regression_identified",
                ),
            ),
            retry_count=1,
            total_latency_ms=7100.0,
            model_latency_ms=2900.0,
            input_tokens=4300,
            output_tokens=640,
            cost_usd=0.024,
        ),
        local_only_fields=("test log snippets", "commit messages"),
    ),
    Scenario(
        scenario_id="ref-ci-03-fix-without-evidence",
        title="Agent proposes a fix branch without classification evidence",
        category="policy_failure",
        request=TriageRequest(
            pull_request_id=PR_1482.id,
            check_run_id=CHECK_RUN.id,
            trigger="workflow_run: test-linux failed on pr/1482",
        ),
        workflow_context=WorkflowContext(
            workflow=WORKFLOW,
            workflow_version=WORKFLOW_VERSION,
            routing_instructions_version="1",
            answer_instructions_version="1",
            model_provider=MODEL_PROVIDER,
            model_name="gpt-5.2",
        ),
        initial_state=CiState(
            repositories=(CHECKOUT_REPO,),
            pull_requests=(PR_1482,),
            check_runs=(CHECK_RUN,),
            test_results=(TEST_FLAKY,),
            commits=(COMMIT_HEAD,),
            issues=(),
        ),
        eligible_actions=tuple(tool.name for tool in TOOLS),
        expected_behavior=ExpectedBehavior(
            outcome="blocked",
            reason_codes=("ungrounded_classification", "confirmation_required"),
            classification_grounded=False,
            permitted_state_transitions=(),
            budgets={"performance_budget_ms": 10000},
            note=(
                "The agent wants to create a fix branch for the flaky test "
                "without run-history evidence and without a confirmed "
                "classification. The guard rejects the branch creation: "
                "confirmation.required=true and confirmation.verified=false. "
                "No comment, issue, or branch may be created."
            ),
        ),
        original_production_behavior=OriginalProductionBehavior(
            outcome="blocked",
            reason_code="ungrounded_classification",
            source="fixture:langsmith",
            note="Production blocked the same branch creation at the guard.",
        ),
        required_dependency_coverage=(
            DependencyCoverage(
                dependency="github",
                kind="stateful",
                tools=("read_failing_checks", "read_test_logs", "create_fix_branch"),
            ),
            DependencyCoverage(
                dependency="issue.retrieval",
                kind="recorded",
                tools=("search_known_issues",),
            ),
        ),
        evidence=TraceFacts(
            source_platform="langsmith",
            trace_id="ref-ci-03-fix-without-evidence",
            outcome="blocked",
            reason_code="ungrounded_classification",
            dependency_calls=(
                DependencyCall(kind="tool", name="read_test_logs", duration_ms=250.0),
                DependencyCall(
                    kind="tool",
                    name="create_fix_branch",
                    error_code="confirmation_required",
                    duration_ms=14.0,
                ),
            ),
            policy_decisions=(
                PolicyDecision(
                    version="classifier-v2",
                    decision="flaky",
                    reason_code="flaky_identified",
                ),
            ),
            confirmation=Confirmation(required=True, verified=False),
            retry_count=0,
            total_latency_ms=2900.0,
            model_latency_ms=1500.0,
            input_tokens=3400,
            output_tokens=420,
            cost_usd=0.017,
        ),
        local_only_fields=("test log snippets", "commit messages"),
    ),
)

for _scenario in SCENARIOS:
    _scenario.content_hash = compute_content_hash(_scenario)
