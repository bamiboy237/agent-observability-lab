# Reference Workflows

Three realistic 2026 agentic workflows for the agent simulation lab, designed
as reference content alongside the existing customer-support workflow. Each
subpackage contains one design document (`DESIGN.md`) and one deterministic,
offline-runnable fixture module (`fixtures.py`). The reference workflows do
not modify or import lab simulation code; a future lab phase can parameterize
the evidence/scenario/bundle contracts from the mapped shapes documented in
each design file.

| Workflow | Directory | Domain | Comparison variable |
| --- | --- | --- | --- |
| Incident-response on-call agent | `incident_response/` | SRE: runbook-driven alert handling, blast-radius guards, paging | runbook retrieval strategy (keyword vs semantic) |
| CI failure triage agent | `ci_triage/` | Developer tooling: flaky vs regression classification, triage reports, fix branches | failure classifier model (gpt-4.1-mini vs gpt-5.2) |
| Claim denial management agent | `claims_denial/` | Healthcare RCM: policy-grounded appeals, gap analysis, autonomy gates | appeal autonomy level (human-confirm vs auto-submit at score >= 0.8) |

## Design shared by all three

- **Stateful system**: each workflow owns a small set of versioned records
  (incidents/runbooks, PRs/check runs, claims/policies/appeals) with explicit
  status machines. The lab seeds an ephemeral copy; nothing is shared.
- **Tools split into safe and sensitive**: read-only tools are free;
  state-changing and external-effect tools are gated, and the highest-risk
  actions require a confirmation that lives in a trusted field the model
  cannot set.
- **One baseline/candidate variable per workflow**, run as the same scenario
  twice (the lab's phase2-08 two-trace pattern): retrieval strategy, model,
  or autonomy policy.
- **Failure categories map to the lab's `SimulationCategory`**: retrieval
  failure, infrastructure failure (one-time timeout with retry), policy
  failure (guard/confirmation blocks), answer failure (misclassification).

## Fixture data contract

Each `fixtures.py` module:

- imports only the standard library and pydantic, so it loads in any offline
  environment;
- derives every identifier with `uuid5` from a per-workflow namespace, so
  repeated imports produce identical data and identical content hashes;
- exposes `WORKFLOW`, `WORKFLOW_VERSION`, `TOOLS`, `SAFE_TOOLS`,
  `SENSITIVE_TOOLS`, `SCENARIOS`, `EVIDENCE_TRACE_IDS`, and
  `compute_content_hash(scenario)`;
- mirrors the lab contract shapes in workflow-local models: scenario
  (`Scenario`), expected behavior (`ExpectedBehavior`), original production
  behavior, dependency coverage, and a compact `TraceFacts` projection of
  `TraceEvidence` (dependency calls, policy decisions, confirmation, retry
  count, timing, tokens, cost).

## Verify offline

```bash
uv run python -c "import app.domain.reference_workflows.incident_response.fixtures"
uv run python -c "import app.domain.reference_workflows.ci_triage.fixtures"
uv run python -c "import app.domain.reference_workflows.claims_denial.fixtures"
```

Each import validates every scenario with pydantic and computes its content
hash; identical imports always yield identical hashes.

## Related reference workflows

This directory is shared: other builders may contribute additional reference
workflows as flat fixture modules (for example `returns_resolution.py`,
`onboarding.py`, `disputes.py`) with design documents under
`docs/reference_workflows/`. The package `__init__.py` stays docstring-only so
every module remains importable.

## Boundaries

- These are reference designs and fixture data, not lab code: nothing in
  `src/app/domain/simulation`, `evidence`, or `bundle` was changed.
- Each workflow is bounded to one agent turn, offline-runnable, and free of
  real external side effects (paging, PR comments, appeal submissions are all
  simulated or recorded).
- 2026 grounding and primary sources are cited in each `DESIGN.md`.
