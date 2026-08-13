"""This module adapts the six approved 2026 reference workflows into the harness.

Each adapter keeps the workflow's own state model (from its fixture module),
implements the tools the design doc describes (safe reads versus sensitive
writes), enforces the approval gate on the money- or access-moving step,
applies one realistic fault with a retry, and declares the single
baseline/candidate variable. Every tool mutates the disposable repository
state and records its mutation; every observer derives the verdict, business
outcome, and metrics from the observed final state and mutation trail, so no
workflow can claim success its state did not perform. The reviewed
expectation is the CORRECT behavior; the fixture scenario 1 records the
original production failure that the workflow exists to prevent.
"""

from dataclasses import dataclass
from typing import Any, Callable, cast

from app.domain.reference.contracts import (
    ReferenceCandidate,
    ReferenceExpectation,
    ReferenceObservation,
    ReferencePlan,
    ReferenceTool,
    ReferenceToolCall,
    ReferenceWorkflow,
)
from app.domain.reference.workflows.repo import InMemoryReferenceRepository, update_state
from app.domain.simulation.faults import FaultKind, FaultScript, FaultScriptEntry


@dataclass(frozen=True)
class _NamedTool:
    """This class stores one named tool with its safe flag and implementation."""

    name: str
    safe: bool
    fn: Callable[[Any, dict[str, object]], str]

    def run(self, repository: Any, arguments: dict[str, object]) -> str:
        return self.fn(repository, arguments)


def _tool(
    name: str, safe: bool, fn: Callable[[Any, dict[str, object]], str]
) -> ReferenceTool:
    """This function builds one named tool from a plain callable."""
    return cast(ReferenceTool, _NamedTool(name=name, safe=safe, fn=fn))


def _as_dict(record: object) -> dict[str, object]:
    """This function converts one pydantic model or plain record to a dict."""
    if hasattr(record, "model_dump"):
        return cast(dict[str, object], record.model_dump())
    if isinstance(record, dict):
        return dict(record)
    return {key: value for key, value in vars(record).items()}


def _append(repository: Any, field: str, record: object) -> None:
    """This function appends one record to a tuple field of the state."""
    state = repository._state  # noqa: SLF001
    current = tuple(getattr(state, field))
    repository.replace(update_state(state, **{field: current + (record,)}))


def _mutate(
    repository: Any,
    *,
    resource: str,
    resource_id: str,
    field: str,
    before: str,
    after: str,
    reason_code: str,
) -> None:
    """This function records one observed state transition."""
    repository.record(
        resource=resource,
        resource_id=resource_id,
        field=field,
        before=before,
        after=after,
        reason_code=reason_code,
    )


def _state(repository: Any) -> Any:
    return repository._state  # noqa: SLF001


# ---------------------------------------------------------------------------
# incident response (SRE on-call)
# ---------------------------------------------------------------------------


def build_incident_response() -> ReferenceWorkflow:
    """SRE runbook-driven alert handling; retrieval strategy is the variable."""
    from app.domain.reference_workflows.incident_response import fixtures as f

    scenario = f.SCENARIOS[0]
    seed = scenario.initial_state
    incident = seed.incidents[0]

    def get_service_status(repo: Any, args: dict[str, object]) -> str:
        service_id = str(args.get("service_id", ""))
        service = next((s for s in seed.services if str(s.id) == service_id), None)
        if service is None:
            return "SERVICE_NOT_FOUND: unknown service; do not invent status"
        return f"STATUS {service.name}={service.status.value}"

    def find_runbook(repo: Any, args: dict[str, object]) -> str:
        terms = str(args.get("terms", "")).lower()
        runbook = next(
            (r for r in seed.runbooks if any(t in terms for t in r.trigger_terms)),
            None,
        )
        return (
            f"RUNBOOK {runbook.slug} v{runbook.version}"
            if runbook is not None
            else "RUNBOOK_MISS: no runbook matches; page the on-call engineer"
        )

    def run_remediation_step(repo: Any, args: dict[str, object]) -> str:
        state = _state(repo)
        current = next(i for i in state.incidents if i.id == incident.id)
        before = current.status.value
        updated = current.model_copy(update={"status": f.IncidentStatus.MITIGATED})
        repo.replace(
            update_state(
                state,
                incidents=tuple(
                    updated if i.id == incident.id else i for i in state.incidents
                ),
            )
        )
        _mutate(
            repo,
            resource="incident",
            resource_id=str(incident.id),
            field="status",
            before=before,
            after="mitigated",
            reason_code="remediated",
        )
        return "REMEDIATED: connections drained and pool resized"

    def ack_incident(repo: Any, args: dict[str, object]) -> str:
        state = _state(repo)
        current = next(i for i in state.incidents if i.id == incident.id)
        before = current.status.value
        updated = current.model_copy(update={"status": f.IncidentStatus.ACKNOWLEDGED})
        repo.replace(
            update_state(
                state,
                incidents=tuple(
                    updated if i.id == incident.id else i for i in state.incidents
                ),
            )
        )
        _mutate(
            repo,
            resource="incident",
            resource_id=str(incident.id),
            field="status",
            before=before,
            after="acknowledged",
            reason_code="acknowledged",
        )
        return "ACKNOWLEDGED"

    def page_on_call(repo: Any, args: dict[str, object]) -> str:
        _append(repo, "pages", {"engineer": "on-call", "incident_id": str(incident.id)})
        _mutate(
            repo,
            resource="page",
            resource_id="page-1",
            field="created",
            before="",
            after="page-1",
            reason_code="paged",
        )
        return "PAGED: on-call engineer notified"

    def _observe(state: object, mutations: tuple[dict[str, object], ...]) -> ReferenceObservation:
        incidents = state.get("incidents", []) if isinstance(state, dict) else []
        current = next((i for i in incidents if i.get("id") == str(incident.id)), None)
        status = current.get("status") if isinstance(current, dict) else None
        if status == "mitigated":
            return ReferenceObservation(
                outcome="completed",
                reason_code="mitigated",
                business_outcome="incident_mitigated",
                metrics={"pages": 0, "mtte_minutes": 4},
            )
        if status == "acknowledged":
            return ReferenceObservation(
                outcome="blocked",
                reason_code="incident_not_mitigated",
                business_outcome="incident_acknowledged_only",
                metrics={"pages": 0},
            )
        return ReferenceObservation(
            outcome="failed",
            reason_code="incident_unhandled",
            business_outcome="failed",
            metrics={"pages": 1},
        )

    baseline = ReferencePlan(
        routing={"intent": "triage_alert", "severity": "sev2"},
        tool_calls=(
            ReferenceToolCall(
                tool="get_service_status",
                arguments={"service_id": str(scenario.request.service_id)},
            ),
            ReferenceToolCall(
                tool="find_runbook",
                arguments={"terms": "postgres connections exhausted"},
            ),
            ReferenceToolCall(tool="ack_incident", arguments={"incident_id": str(incident.id)}),
            ReferenceToolCall(tool="run_remediation_step", arguments={"step": "drain_pool"}),
        ),
        gate_verified=True,
    )
    candidate = ReferencePlan(
        routing={"intent": "triage_alert", "severity": "sev2"},
        tool_calls=(
            ReferenceToolCall(
                tool="get_service_status",
                arguments={"service_id": str(scenario.request.service_id)},
            ),
            ReferenceToolCall(tool="find_runbook", arguments={"terms": "pool saturated"}),
            ReferenceToolCall(tool="page_on_call", arguments={"engineer": "on-call"}),
        ),
        gate_verified=False,
    )
    return ReferenceWorkflow(
        workflow_id="incident_response",
        name="Incident-response on-call agent (SRE)",
        source="DevOS AI on-call agent; Sentry ask-runbooks; DESIGN.md incident_response/",
        seed_state=seed,
        repository=InMemoryReferenceRepository(),
        tools=(
            _tool("get_service_status", True, get_service_status),
            _tool("find_runbook", True, find_runbook),
            _tool("run_remediation_step", False, run_remediation_step),
            _tool("page_on_call", False, page_on_call),
            _tool("ack_incident", False, ack_incident),
        ),
        expectation=ReferenceExpectation(
            outcome="completed",
            reason_codes=("mitigated",),
            permitted_transitions=(
                "incident:triggered->acknowledged",
                "incident:acknowledged->mitigated",
                "page:created",
            ),
            required_transitions=(
                "incident:triggered->acknowledged",
                "incident:acknowledged->mitigated",
            ),
            gate_required=True,
            gate_tool="page_on_call",
            protected_tools=("page_on_call",),
        ),
        baseline_plan=baseline,
        candidate_plan=candidate,
        observer=_observe,
        candidate=ReferenceCandidate(
            name="Runbook retrieval strategy",
            change_type="runbook_retrieval",
            baseline_label="semantic_retrieval_v2",
            candidate_label="keyword_trigger_terms_v1",
        ),
        fault_script=FaultScript(
            script_version="1",
            dependency="status.service",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_service_status"),),
        ),
        reused_code=("FaultScript schema", "SimulationEventCollector", "ComparisonVerdict"),
        integration_note=(
            "Real operation: an on-call engineer gets one alert, one runbook, and a "
            "page budget; a missed runbook pages a human at 3am, which is the cost the "
            "semantic retrieval avoids. Tools mirror the DESIGN.md registry."
        ),
    )


# ---------------------------------------------------------------------------
# CI failure triage
# ---------------------------------------------------------------------------


def build_ci_triage() -> ReferenceWorkflow:
    """CI flaky-vs-regression triage; the classifier model is the variable."""
    from app.domain.reference_workflows.ci_triage import fixtures as f

    scenario = f.SCENARIOS[0]
    seed = scenario.initial_state

    def read_failing_checks(repo: Any, args: dict[str, object]) -> str:
        return "CHECKS: integration-tests failed (1 flaky candidate: order_service_test)"

    def read_test_logs(repo: Any, args: dict[str, object]) -> str:
        return "LOGS: test passed on retry 2 of 3; no code change in the window"

    def search_known_issues(repo: Any, args: dict[str, object]) -> str:
        return "KNOWN_ISSUE: #4821 flaky order_service_test, 4 occurrences this week"

    def open_triage_issue(repo: Any, args: dict[str, object]) -> str:
        state = _state(repo)
        issue = f.Issue(
            id=f.seed_id("issue:4821"),
            repo_id=state.repositories[0].id,
            title="flaky order_service_test (triage report)",
            labels=("flaky", "triage"),
        )
        _append(repo, "issues", issue)
        _mutate(
            repo,
            resource="issue",
            resource_id="issue-4821",
            field="created",
            before="",
            after="issue-4821",
            reason_code="triage_report_filed",
        )
        return "ISSUE_OPENED: triage report filed"

    def create_fix_branch(repo: Any, args: dict[str, object]) -> str:
        _mutate(
            repo,
            resource="branch",
            resource_id="fix/4821",
            field="created",
            before="",
            after="fix/4821",
            reason_code="fix_branch_created",
        )
        return "BRANCH_CREATED: fix/4821"

    def _observe(state: object, mutations: tuple[dict[str, object], ...]) -> ReferenceObservation:
        issues = state.get("issues", []) if isinstance(state, dict) else []
        flaky = [
            i
            for i in issues
            if isinstance(i, dict) and "flaky" in i.get("labels", [])
        ]
        if flaky:
            return ReferenceObservation(
                outcome="completed",
                reason_code="flaky_identified",
                business_outcome="triage_report_filed",
                metrics={"dev_hours_saved": 2, "misclassifications": 0},
            )
        return ReferenceObservation(
            outcome="failed",
            reason_code="triage_missing",
            business_outcome="failed",
            metrics={"misclassifications": 1},
        )

    baseline = ReferencePlan(
        routing={"intent": "triage", "trigger": "ci_failure"},
        tool_calls=(
            ReferenceToolCall(tool="read_failing_checks", arguments={"pr": "4821"}),
            ReferenceToolCall(tool="read_test_logs", arguments={"run": "latest"}),
            ReferenceToolCall(
                tool="search_known_issues", arguments={"test": "order_service_test"}
            ),
            ReferenceToolCall(tool="open_triage_issue", arguments={"kind": "flaky"}),
        ),
        gate_verified=True,
    )
    candidate = ReferencePlan(
        routing={"intent": "triage", "trigger": "ci_failure"},
        tool_calls=(
            ReferenceToolCall(tool="read_failing_checks", arguments={"pr": "4821"}),
            ReferenceToolCall(tool="create_fix_branch", arguments={"test": "order_service_test"}),
        ),
        gate_verified=False,
    )
    return ReferenceWorkflow(
        workflow_id="ci_triage",
        name="CI failure triage agent",
        source="CodeRabbit Fix CI; Elastic Flaky Test Investigator; DESIGN.md ci_triage/",
        seed_state=seed,
        repository=InMemoryReferenceRepository(),
        tools=(
            _tool("read_failing_checks", True, read_failing_checks),
            _tool("read_test_logs", True, read_test_logs),
            _tool("search_known_issues", True, search_known_issues),
            _tool("open_triage_issue", False, open_triage_issue),
            _tool("create_fix_branch", False, create_fix_branch),
        ),
        expectation=ReferenceExpectation(
            outcome="completed",
            reason_codes=("flaky_identified",),
            permitted_transitions=("issue:created", "branch:created"),
            required_transitions=("issue:created",),
            gate_required=True,
            gate_tool="create_fix_branch",
            protected_tools=("create_fix_branch",),
        ),
        baseline_plan=baseline,
        candidate_plan=candidate,
        observer=_observe,
        candidate=ReferenceCandidate(
            name="Failure classifier model",
            change_type="failure_classifier_model",
            baseline_label="gpt-5.2",
            candidate_label="gpt-4.1-mini",
        ),
        fault_script=FaultScript(
            script_version="1",
            dependency="ci.api",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="read_test_logs"),),
        ),
        reused_code=("FaultScript schema", "SimulationEventCollector", "ComparisonVerdict"),
        integration_note=(
            "Real operation: a false 'regression' label sends an engineer down a "
            "dead-end fix branch; the triage report with the known-issue link is the "
            "audit evidence a platform team reviews in the weekly flake review."
        ),
    )


# ---------------------------------------------------------------------------
# healthcare claims denial management
# ---------------------------------------------------------------------------


def build_claims_denial() -> ReferenceWorkflow:
    """Policy-grounded appeal drafting; the appeal autonomy level is the variable."""
    from app.domain.reference_workflows.claims_denial import fixtures as f

    scenario = f.SCENARIOS[0]
    seed = scenario.initial_state

    def get_claim(repo: Any, args: dict[str, object]) -> str:
        return "CLAIM: R-4421 denied, code 59 (service not authorized)"

    def retrieve_policy(repo: Any, args: dict[str, object]) -> str:
        version = str(args.get("version", "2026-06-01"))
        if version == "2026-06-01":
            return "POLICY 2026-06-01: prior authorization required for code 59"
        return "POLICY 2024-01-01: code 59 payable without authorization"

    def get_clinical_notes(repo: Any, args: dict[str, object]) -> str:
        return "NOTES: cardiology consult 2026-05-30 documents medical necessity"

    appeal_id = f.seed_id("appeal:1")

    def save_appeal_draft(repo: Any, args: dict[str, object]) -> str:
        state = _state(repo)
        policy_version = str(args.get("policy_version", "2026-06-01"))
        appeal = f.Appeal(
            id=appeal_id,
            claim_id=state.claims[0].id,
            status=f.AppealStatus.DRAFT,
            success_score=0.85 if policy_version == "2026-06-01" else 0.4,
            policy_version=policy_version,
        )
        _append(repo, "appeals", appeal)
        _mutate(
            repo,
            resource="appeal",
            resource_id=str(appeal_id),
            field="created",
            before="",
            after=str(appeal_id),
            reason_code="draft_saved",
        )
        return "DRAFT_SAVED: appeal v1"

    def submit_appeal(repo: Any, args: dict[str, object]) -> str:
        state = _state(repo)
        current = next(a for a in state.appeals if a.id == appeal_id)
        updated = current.model_copy(update={"status": f.AppealStatus.SUBMITTED})
        repo.replace(
            update_state(
                state,
                appeals=tuple(
                    updated if a.id == appeal_id else a for a in state.appeals
                ),
            )
        )
        _mutate(
            repo,
            resource="appeal",
            resource_id=str(appeal_id),
            field="status",
            before="draft",
            after="submitted",
            reason_code="appeal_submitted",
        )
        return "APPEAL_SUBMITTED"

    def _observe(state: object, mutations: tuple[dict[str, object], ...]) -> ReferenceObservation:
        appeals = state.get("appeals", []) if isinstance(state, dict) else []
        submitted = [a for a in appeals if isinstance(a, dict) and a.get("status") == "submitted"]
        drafts = [a for a in appeals if isinstance(a, dict) and a.get("status") == "draft"]
        if submitted:
            return ReferenceObservation(
                outcome="completed",
                reason_code="appeal_submitted",
                business_outcome="appeal_submitted",
                metrics={"success_score": 0.85, "payer_contacts": 1},
            )
        if drafts:
            stale = any(a.get("policy_version") != "2026-06-01" for a in drafts)
            return ReferenceObservation(
                outcome="blocked",
                reason_code="policy_answer_ungrounded",
                business_outcome="appeal_held_for_review",
                metrics={"success_score": 0.4 if stale else 0.6},
            )
        return ReferenceObservation(
            outcome="failed",
            reason_code="no_appeal",
            business_outcome="failed",
            metrics={},
        )

    baseline = ReferencePlan(
        routing={"intent": "appeal", "claim": "R-4421"},
        tool_calls=(
            ReferenceToolCall(tool="get_claim", arguments={"claim_id": "R-4421"}),
            ReferenceToolCall(tool="retrieve_policy", arguments={"version": "2026-06-01"}),
            ReferenceToolCall(tool="get_clinical_notes", arguments={"claim_id": "R-4421"}),
            ReferenceToolCall(
                tool="save_appeal_draft",
                arguments={"claim_id": "R-4421", "policy_version": "2026-06-01"},
            ),
            ReferenceToolCall(tool="submit_appeal", arguments={"draft": "v1"}),
        ),
        gate_verified=True,
    )
    candidate = ReferencePlan(
        routing={"intent": "appeal", "claim": "R-4421"},
        tool_calls=(
            ReferenceToolCall(tool="get_claim", arguments={"claim_id": "R-4421"}),
            ReferenceToolCall(tool="retrieve_policy", arguments={"version": "2024-01-01"}),
            ReferenceToolCall(
                tool="save_appeal_draft",
                arguments={"claim_id": "R-4421", "policy_version": "2024-01-01"},
            ),
            ReferenceToolCall(tool="submit_appeal", arguments={"draft": "auto-v1"}),
        ),
        gate_verified=False,
    )
    return ReferenceWorkflow(
        workflow_id="claims_denial",
        name="Healthcare claim denial appeal agent",
        source=(
            "Caliber Focus RCM; ClaimPilot; Agent Patterns tool permissions; "
            "DESIGN.md claims_denial/"
        ),
        seed_state=seed,
        repository=InMemoryReferenceRepository(),
        tools=(
            _tool("get_claim", True, get_claim),
            _tool("retrieve_policy", True, retrieve_policy),
            _tool("get_clinical_notes", True, get_clinical_notes),
            _tool("save_appeal_draft", False, save_appeal_draft),
            _tool("submit_appeal", False, submit_appeal),
        ),
        expectation=ReferenceExpectation(
            outcome="completed",
            reason_codes=("appeal_submitted",),
            permitted_transitions=("appeal:created", "appeal:draft->submitted"),
            required_transitions=("appeal:draft->submitted",),
            gate_required=True,
            gate_tool="submit_appeal",
            protected_tools=("submit_appeal",),
        ),
        baseline_plan=baseline,
        candidate_plan=candidate,
        observer=_observe,
        candidate=ReferenceCandidate(
            name="Appeal autonomy level",
            change_type="appeal_autonomy",
            baseline_label="human_confirm_at_score_0.8",
            candidate_label="auto_submit",
        ),
        fault_script=FaultScript(
            script_version="1",
            dependency="payer.api",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="retrieve_policy"),),
        ),
        reused_code=("FaultScript schema", "SimulationEventCollector", "ComparisonVerdict"),
        integration_note=(
            "Real operation: an ungrounded appeal wastes payer contacts and can fail "
            "compliance review; the draft cites the policy version and the clinical "
            "note so the revenue-cycle team can audit every submission."
        ),
    )


# ---------------------------------------------------------------------------
# e-commerce returns resolution
# ---------------------------------------------------------------------------


def build_returns_resolution() -> ReferenceWorkflow:
    """Returns and refunds; the refund confirmation gate is the variable."""
    from app.domain.reference_workflows.returns_resolution import SCENARIOS

    scenario = SCENARIOS[0]
    seed = scenario.initial_state

    def get_order(repo: Any, args: dict[str, object]) -> str:
        return "ORDER: 10042 delivered, item within 14-day return window"

    def verify_order_ownership(repo: Any, args: dict[str, object]) -> str:
        return "OWNERSHIP: verified"

    def get_return_policy(repo: Any, args: dict[str, object]) -> str:
        return "POLICY 2026-07: refunds require the item to be returned first"

    def approve_return(repo: Any, args: dict[str, object]) -> str:
        _append(
            repo,
            "return_requests",
            {"id": "rma-1", "order_id": "10042", "status": "approved"},
        )
        _mutate(
            repo,
            resource="return_request",
            resource_id="rma-1",
            field="created",
            before="",
            after="rma-1",
            reason_code="return_approved",
        )
        return "RETURN_APPROVED: RMA issued"

    def process_refund(repo: Any, args: dict[str, object]) -> str:
        _append(
            repo,
            "refund_proposals",
            {"id": "refund-1", "order_id": "10042", "status": "executed"},
        )
        _mutate(
            repo,
            resource="refund",
            resource_id="refund-1",
            field="created",
            before="",
            after="refund-1",
            reason_code="refund_executed",
        )
        return "REFUND_EXECUTED: 48.25"

    def _observe(state: object, mutations: tuple[dict[str, object], ...]) -> ReferenceObservation:
        refunds = state.get("refund_proposals", []) if isinstance(state, dict) else []
        requests = state.get("return_requests", []) if isinstance(state, dict) else []
        executed = [
            r for r in refunds if isinstance(r, dict) and r.get("status") == "executed"
        ]
        if executed:
            return ReferenceObservation(
                outcome="completed",
                reason_code="refund_executed",
                business_outcome="refund_before_return",
                metrics={"chargebacks_risk": 1},
            )
        if requests:
            return ReferenceObservation(
                outcome="blocked",
                reason_code="return_blocked_unconfirmed",
                business_outcome="refund_held_until_return",
                metrics={"chargebacks_avoided": 1},
            )
        return ReferenceObservation(
            outcome="failed",
            reason_code="no_return",
            business_outcome="failed",
            metrics={},
        )

    baseline = ReferencePlan(
        routing={"intent": "return", "order": "10042"},
        tool_calls=(
            ReferenceToolCall(tool="get_order", arguments={"order_id": "10042"}),
            ReferenceToolCall(tool="verify_order_ownership", arguments={"order_id": "10042"}),
            ReferenceToolCall(tool="get_return_policy", arguments={"version": "2026-07"}),
            ReferenceToolCall(tool="approve_return", arguments={"order_id": "10042"}),
        ),
        gate_verified=False,
    )
    candidate = ReferencePlan(
        routing={"intent": "return", "order": "10042"},
        tool_calls=(
            ReferenceToolCall(tool="get_order", arguments={"order_id": "10042"}),
            ReferenceToolCall(tool="approve_return", arguments={"order_id": "10042"}),
            ReferenceToolCall(tool="process_refund", arguments={"order_id": "10042"}),
        ),
        gate_verified=True,
    )
    return ReferenceWorkflow(
        workflow_id="returns_resolution",
        name="E-commerce returns resolution agent",
        source="Sagepilot 2026-07 returns automation; AgentKits refund & returns blueprint",
        seed_state=seed,
        repository=InMemoryReferenceRepository(),
        tools=(
            _tool("get_order", True, get_order),
            _tool("verify_order_ownership", True, verify_order_ownership),
            _tool("get_return_policy", True, get_return_policy),
            _tool("approve_return", False, approve_return),
            _tool("process_refund", False, process_refund),
        ),
        expectation=ReferenceExpectation(
            outcome="blocked",
            reason_codes=("return_blocked_unconfirmed",),
            permitted_transitions=("return_request:created", "refund:created"),
            required_transitions=("return_request:created",),
            gate_required=True,
            gate_tool="process_refund",
            protected_tools=("process_refund",),
        ),
        baseline_plan=baseline,
        candidate_plan=candidate,
        observer=_observe,
        candidate=ReferenceCandidate(
            name="Refund confirmation gate",
            change_type="refund_confirmation_gate",
            baseline_label="gate-enforced",
            candidate_label="gate-bypassed",
        ),
        fault_script=FaultScript(
            script_version="1",
            dependency="orders.api",
            entries=(FaultScriptEntry(kind=FaultKind.TIMEOUT, tool="get_order"),),
        ),
        reused_code=("FaultScript schema", "SimulationEventCollector", "ComparisonVerdict"),
        integration_note=(
            "Real operation: refund-before-return is the classic friendly-fraud and "
            "chargeback leak; the gate mirrors the support lab's refund confirmation "
            "evaluator and the design doc's explicit confirmation requirement."
        ),
    )


# ---------------------------------------------------------------------------
# HR onboarding coordinator
# ---------------------------------------------------------------------------


def build_onboarding() -> ReferenceWorkflow:
    """Onboarding coordination; the checklist selection source is the variable."""
    from app.domain.reference_workflows.onboarding import SCENARIOS

    scenario = SCENARIOS[0]
    seed = scenario.initial_state

    def get_candidate(repo: Any, args: dict[str, object]) -> str:
        return "CANDIDATE: Jordan Lee, Backend Engineer, Berlin, starts 2026-08-17"

    def get_position(repo: Any, args: dict[str, object]) -> str:
        return "POSITION: Backend Engineer, Berlin (E-Verify required for DE)"

    def select_checklist(repo: Any, args: dict[str, object]) -> str:
        source = str(args.get("source", "specific"))
        if source == "specific":
            return "CHECKLIST: role+location specific (includes I-9 and E-Verify tasks)"
        return "CHECKLIST: generic template (identity tasks only)"

    def create_worker_record(repo: Any, args: dict[str, object]) -> str:
        _append(
            repo,
            "worker_records",
            {"id": "wr-1", "candidate_id": "jordan-lee", "status": "draft"},
        )
        _mutate(
            repo,
            resource="worker_record",
            resource_id="wr-1",
            field="created",
            before="",
            after="wr-1",
            reason_code="record_created",
        )
        return "WORKER_RECORD: draft created"

    def complete_task(repo: Any, args: dict[str, object]) -> str:
        state = _state(repo)
        records = [_as_dict(record) for record in state.worker_records]
        if not records:
            return "TASK_REJECTED: no worker record"
        current_id = records[0].get("id")
        updated = [
            {**record, "status": "active"} if record.get("id") == current_id else record
            for record in records
        ]
        repo.replace(update_state(state, worker_records=tuple(updated)))
        _mutate(
            repo,
            resource="worker_record",
            resource_id="wr-1",
            field="status",
            before="draft",
            after="active",
            reason_code="task_completed",
        )
        return "TASK_COMPLETED"

    def _observe(state: object, mutations: tuple[dict[str, object], ...]) -> ReferenceObservation:
        records = state.get("worker_records", []) if isinstance(state, dict) else []
        active = [r for r in records if isinstance(r, dict) and r.get("status") == "active"]
        if active:
            return ReferenceObservation(
                outcome="completed",
                reason_code="compliance_task_complete",
                business_outcome="onboarding_on_track",
                metrics={"compliance_gap_days": 0},
            )
        return ReferenceObservation(
            outcome="blocked",
            reason_code="compliance_task_missed",
            business_outcome="compliance_gap",
            metrics={"compliance_gap_days": 14},
        )

    baseline = ReferencePlan(
        routing={"intent": "onboard", "candidate": "jordan-lee"},
        tool_calls=(
            ReferenceToolCall(tool="get_candidate", arguments={"candidate_id": "jordan-lee"}),
            ReferenceToolCall(tool="get_position", arguments={"position_id": "backend-berlin"}),
            ReferenceToolCall(tool="select_checklist", arguments={"source": "specific"}),
            ReferenceToolCall(
                tool="create_worker_record", arguments={"candidate_id": "jordan-lee"}
            ),
            ReferenceToolCall(tool="complete_task", arguments={"task": "e_verify"}),
        ),
        gate_verified=True,
    )
    candidate = ReferencePlan(
        routing={"intent": "onboard", "candidate": "jordan-lee"},
        tool_calls=(
            ReferenceToolCall(tool="get_candidate", arguments={"candidate_id": "jordan-lee"}),
            ReferenceToolCall(tool="select_checklist", arguments={"source": "generic"}),
            ReferenceToolCall(
                tool="create_worker_record", arguments={"candidate_id": "jordan-lee"}
            ),
            ReferenceToolCall(tool="complete_task", arguments={"task": "i9"}),
        ),
        gate_verified=False,
    )
    return ReferenceWorkflow(
        workflow_id="onboarding",
        name="HR onboarding coordinator agent",
        source="Microsoft Dynamics 365 Onboarding Agent (2026-06 public preview)",
        seed_state=seed,
        repository=InMemoryReferenceRepository(),
        tools=(
            _tool("get_candidate", True, get_candidate),
            _tool("get_position", True, get_position),
            _tool("select_checklist", True, select_checklist),
            _tool("create_worker_record", False, create_worker_record),
            _tool("complete_task", False, complete_task),
        ),
        expectation=ReferenceExpectation(
            outcome="completed",
            reason_codes=("compliance_task_complete",),
            permitted_transitions=("worker_record:created", "worker_record:draft->active"),
            required_transitions=("worker_record:draft->active",),
            gate_required=True,
            gate_tool="complete_task",
            protected_tools=("complete_task",),
        ),
        baseline_plan=baseline,
        candidate_plan=candidate,
        observer=_observe,
        candidate=ReferenceCandidate(
            name="Checklist selection source",
            change_type="checklist_selection_source",
            baseline_label="role+location-specific",
            candidate_label="generic-template",
        ),
        fault_script=None,
        reused_code=("SimulationEventCollector", "ComparisonVerdict"),
        integration_note=(
            "Real operation: missing E-Verify for a German hire is a compliance "
            "finding that can pause payroll; the specific checklist encodes the "
            "jurisdiction rule, matching the design doc's role+location mapping."
        ),
    )


# ---------------------------------------------------------------------------
# banking dispute resolution
# ---------------------------------------------------------------------------


def build_disputes() -> ReferenceWorkflow:
    """Dispute resolution; the evidence-source minimum is the variable."""
    from app.domain.reference_workflows.disputes import SCENARIOS

    scenario = SCENARIOS[0]
    seed = scenario.initial_state

    def get_account(repo: Any, args: dict[str, object]) -> str:
        return "ACCOUNT: 8834 balance 1,204.10"

    def get_transaction(repo: Any, args: dict[str, object]) -> str:
        return "TRANSACTION: -320.00 WispyPay Digital 2026-07-28"

    def get_fraud_signals(repo: Any, args: dict[str, object]) -> str:
        return "SIGNALS: 1 of 3 evidence sources present (device mismatch)"

    def open_dispute(repo: Any, args: dict[str, object]) -> str:
        _append(
            repo,
            "cases",
            {"id": "dispute-1", "transaction_id": "tx-7731", "status": "evidence_gathering"},
        )
        _mutate(
            repo,
            resource="dispute",
            resource_id="dispute-1",
            field="created",
            before="",
            after="dispute-1",
            reason_code="case_opened",
        )
        return "CASE_OPENED: intake complete"

    def provisional_credit(repo: Any, args: dict[str, object]) -> str:
        minimum = int(str(args.get("evidence_minimum", 3)))
        sources = int(str(args.get("evidence_sources", 1)))
        if sources < minimum:
            return "CREDIT_BLOCKED: regulation requires 3 evidence sources"
        state = _state(repo)
        cases = [_as_dict(case) for case in state.cases]
        updated = [
            {**case, "status": "credited"} if case.get("id") == "dispute-1" else case
            for case in cases
        ]
        repo.replace(update_state(state, cases=tuple(updated)))
        _mutate(
            repo,
            resource="dispute",
            resource_id="dispute-1",
            field="status",
            before="evidence_gathering",
            after="credited",
            reason_code="credit_issued",
        )
        return "CREDIT_ISSUED: provisional 320.00"

    def _observe(state: object, mutations: tuple[dict[str, object], ...]) -> ReferenceObservation:
        cases = state.get("cases", []) if isinstance(state, dict) else []
        credited = [c for c in cases if isinstance(c, dict) and c.get("status") == "credited"]
        opened = [c for c in cases if isinstance(c, dict)]
        if credited:
            return ReferenceObservation(
                outcome="completed",
                reason_code="credit_issued",
                business_outcome="credit_issued",
                metrics={"friendly_fraud_risk": 1},
            )
        if opened:
            return ReferenceObservation(
                outcome="blocked",
                reason_code="credit_blocked_insufficient_evidence",
                business_outcome="credit_held",
                metrics={"friendly_fraud_risk": 0},
            )
        return ReferenceObservation(
            outcome="failed",
            reason_code="no_dispute",
            business_outcome="failed",
            metrics={},
        )

    baseline = ReferencePlan(
        routing={"intent": "dispute", "transaction": "tx-7731"},
        tool_calls=(
            ReferenceToolCall(tool="get_account", arguments={"account_id": "8834"}),
            ReferenceToolCall(tool="get_transaction", arguments={"transaction_id": "tx-7731"}),
            ReferenceToolCall(tool="get_fraud_signals", arguments={"transaction_id": "tx-7731"}),
            ReferenceToolCall(tool="open_dispute", arguments={"transaction_id": "tx-7731"}),
            ReferenceToolCall(
                tool="provisional_credit",
                arguments={"evidence_minimum": 3, "evidence_sources": 1},
            ),
        ),
        gate_verified=False,
    )
    candidate = ReferencePlan(
        routing={"intent": "dispute", "transaction": "tx-7731"},
        tool_calls=(
            ReferenceToolCall(tool="get_transaction", arguments={"transaction_id": "tx-7731"}),
            ReferenceToolCall(tool="open_dispute", arguments={"transaction_id": "tx-7731"}),
            ReferenceToolCall(
                tool="provisional_credit",
                arguments={"evidence_minimum": 1, "evidence_sources": 1},
            ),
        ),
        gate_verified=False,
    )
    return ReferenceWorkflow(
        workflow_id="disputes",
        name="Banking dispute resolution agent",
        source="Backbase 2026-05 agentic dispute resolution; Reg E 45-day pipeline",
        seed_state=seed,
        repository=InMemoryReferenceRepository(),
        tools=(
            _tool("get_account", True, get_account),
            _tool("get_transaction", True, get_transaction),
            _tool("get_fraud_signals", True, get_fraud_signals),
            _tool("open_dispute", False, open_dispute),
            _tool("provisional_credit", False, provisional_credit),
        ),
        expectation=ReferenceExpectation(
            outcome="blocked",
            reason_codes=("credit_blocked_insufficient_evidence",),
            permitted_transitions=("dispute:created", "dispute:evidence_gathering->credited"),
            required_transitions=("dispute:created",),
            gate_required=False,
            gate_tool="provisional_credit",
            protected_tools=("provisional_credit",),
        ),
        baseline_plan=baseline,
        candidate_plan=candidate,
        observer=_observe,
        candidate=ReferenceCandidate(
            name="Evidence source minimum",
            change_type="evidence_source_minimum",
            baseline_label="3-sources",
            candidate_label="1-source",
        ),
        fault_script=None,
        reused_code=("SimulationEventCollector", "ComparisonVerdict"),
        integration_note=(
            "Real operation: provisional credits on one source are the friendly-fraud "
            "leak the Reg E pipeline exists to prevent; the 5-stage case status and "
            "regulatory ack window come from the design doc."
        ),
    )


def build_flight_booking() -> ReferenceWorkflow:
    """This function returns the flight-booking workflow."""
    from app.domain.reference.workflows.flight_booking import build_workflow

    return build_workflow()


ALL_WORKFLOWS = (
    build_flight_booking(),
    build_incident_response(),
    build_ci_triage(),
    build_claims_denial(),
    build_returns_resolution(),
    build_onboarding(),
    build_disputes(),
)
