# Reference Workflow: Healthcare Claim Denial Management Agent

- Workflow id: `claims_denial_agent`
- Workflow version: `1.2.0`
- Fixture module: `fixtures.py` in this directory
- Status: reference design, offline-runnable, not wired into lab phases

## 1. Domain

The **claim denial management agent** is a 2026 healthcare revenue-cycle
workflow. When a payer denies a claim, the agent reads the claim and the
explanation of benefits (EOB) denial reason, retrieves the payer's medical
policy, runs a gap analysis that compares the clinical notes against the
policy criteria, computes a policy-grounded success score, and then drafts an
appeal, requests missing evidence, or escalates to a human reviewer. Appeals
must cite the exact policy version and the chart evidence for every criterion.

Real-world grounding (2026):

- **Denial management agents** act on the denial instead of waiting:
  "an AI agent for denial management reads the EOB, classifies the root
  cause, drafts a payer-specific appeal, and resubmits, autonomously, the same
  day" (Caliber Focus, *Agentic AI Workflows in Healthcare RCM*,
  https://caliberfocus.com/agentic-ai-workflows-healthcare-rcm).
- **ClaimPilot** is an open-source agent that "analyzes denied insurance
  claims, diagnoses the root cause against retrieved medical policies,
  identifies missing clinical evidence, and generates highly targeted,
  policy-cited appeal letters" with a "Missing Evidence Detection (Gap
  Analysis)" step and a 0-100 percent predictive success score
  (https://github.com/sarvanithin/ClaimPilot).
- **Grounded verification is mandatory**: the agent fetches verbatim policy
  chunks to ground its logic; an appeal that cites a stale or wrong policy is
  worse than no appeal.
- **Autonomy levels** (draft-only vs auto-submit above a score threshold) are
  the 2026 governance question for healthcare agents: the same tool set runs
  under different confirmation policies.

This workflow differs from the other two: the state is patient-facing (claims
and clinical notes), every write has compliance weight, and the comparison
variable is a workflow policy (autonomy level), not retrieval or model choice.

## 2. Turn flow

1. A denial event for one claim triggers the agent.
2. Agent reads the claim and its denial code/reason.
3. Agent retrieves the payer medical policy for the procedure code.
4. Agent reads the clinical notes and runs the gap analysis against the
   policy criteria.
5. Agent computes the success score and searches prior appeals.
6. Grounded actions only: save an appeal draft, request missing evidence,
   escalate, or submit an appeal (gated by the autonomy level).

## 3. Stateful system

Owned system (an ephemeral copy in the lab; records in `fixtures.py`):

| Entity | Key fields | Statuses |
| --- | --- | --- |
| `Payer` | id, name | - |
| `Claim` | id, payer_id, procedure_code, diagnosis_code, status, denial_code, denial_reason, amount, eob_text | submitted, denied, in_review, appealed, paid |
| `Policy` | id, payer_id, slug, version, title, criteria, content | versioned (slug + version unique) |
| `ClinicalNote` | id, claim_id, content | - |
| `Appeal` | id, claim_id, status, success_score, policy_version, missing_evidence | draft, submitted, accepted, rejected |

State machine (claim): `denied -> in_review` (escalation) or
`denied -> appealed` (submission). An appeal starts as `draft` and only
becomes `submitted` when the autonomy gate passes.

Local-only fields (never traced, never bundled): EOB denial text, clinical
note content, policy content.

External dependencies needing recorded fixtures or simulators: payer appeal
submission (`submit_appeal`) and the provider-office contact channel
(`request_missing_evidence`).

## 4. Tools: safe vs sensitive

| Tool | Sensitivity | Confirmation | Why |
| --- | --- | --- | --- |
| `get_claim` | safe | no | read-only |
| `retrieve_policy` | safe | no | retrieval; every appeal must cite the returned version |
| `get_clinical_notes` | safe | no | read-only |
| `search_prior_appeals` | safe | no | read-only |
| `save_appeal_draft` | sensitive | no | state write, but a draft is reversible and reviewable |
| `submit_appeal` | sensitive | yes | external legal effect on the payer; gated by autonomy level and score |
| `request_missing_evidence` | sensitive | yes | contacts a provider office; external effect |
| `escalate_to_reviewer` | sensitive | no | hands the claim to a human; the safe terminal action when grounding fails |

The split follows 2026 healthcare-agent practice: reads are free, anything
that leaves the system (submission, provider contact) is gated, and escalation
is always available as the safe fallback.

## 5. Baseline/candidate comparison variable

**Appeal autonomy level** (`appeal_autonomy_level`):

- Baseline: `human_confirm` — every `submit_appeal` requires explicit human
  confirmation (confirmation.required=true; verified comes from a trusted
  field the model cannot set).
- Candidate: `auto_threshold_0.8` — the agent auto-submits when the
  policy-grounded success score is at least 0.8, without per-submit human
  confirmation.
- Unit: appeals submitted without human review; secondary measures are
  blocked appeals, escalations, and resolution latency.
- Scenario `ref-claims-02-auto-submit-threshold` is the boundary case: the gap
  analysis finds two missing criteria, the score is 0.72, so **both** variants
  must block submission. The comparison measures how the autonomy policy
  changes behavior on the same claim while keeping the safety floor intact.

## 6. Mapping to the lab contracts

### Evidence contract (`TraceEvidence`)

| Lab field | Mapping for this workflow |
| --- | --- |
| `workflow`, `workflow_version` | `claims_denial_agent`, `1.2.0` |
| `outcome` | completed / blocked / escalated / failed |
| `reason_code` | `appeal_drafted`, `appeal_submitted`, `appeal_blocked_below_threshold`, `appeal_blocked_unconfirmed`, `policy_answer_ungrounded`, `escalated_to_reviewer`, `ok_with_retry`, ... |
| `events` | turn, model, tool, retrieval (`retrieve_policy`), database, policy, confirmation, escalation, retry |
| `dependency_calls` | one per tool call; `error_code` values `timeout`, `confirmation_required` |
| `policy_decisions` | one per policy grounding decision (version, decision, reason_code) — the natural home for the success score |
| `confirmation` | required=true for `submit_appeal` and `request_missing_evidence` |
| `task_input` / `task_output` | needs a per-workflow allowlist extension (e.g. `claims.denial.code`, `claims.autonomy.level`, `claims.success.score`) |
| `trace attributes` | needs per-workflow keys in `TRACE_ATTRIBUTE_ALLOWLIST` (e.g. `claims.denial.code`, `claims.policy.grounded`, `claims.autonomy.level`) |

The fixture `TraceFacts` projection carries the decision facts offline.

### Scenario contract (`SimulationScenario`)

| Lab field | Mapping for this workflow |
| --- | --- |
| `scenario_id` | `ref-claims-01-stale-policy` |
| `category` | reuse `SimulationCategory` (`retrieval_failure`, `policy_failure`, `infrastructure_failure`, ...) |
| `request` | `ClaimsRequest` (claim_id, trigger) — `SupportRequest` is support-fixed; needs parameterization |
| `workflow_context` | reuse `WorkflowContext`; the autonomy level is an additional versioned field (`autonomy_level`) |
| `initial_state` | `ClaimsState` (payers, claims, policies, clinical_notes, appeals) |
| `eligible_actions` | the 8 tools above |
| `expected_behavior` | reuse `ExpectedBehavior`; `ExpectedStateTransition.resource` pattern must extend to `claim`, `appeal`, `policy` |
| `original_production_behavior` | reuse unchanged |
| `required_dependency_coverage` | reuse; `claims.database` (stateful), `policy.retrieval` (recorded), `appeal.submission` (recorded) |
| `evidence_ref` | reuse; trace ids like `ref-claims-01-stale-policy` |
| `local_only_fields` | reuse; EOB text, clinical notes, policy content |
| `content_hash` | same canonical-JSON mechanism |

### Bundle contract (`SimulationBundle`)

| Lab field | Mapping for this workflow |
| --- | --- |
| `bundle_id` / `content_hash` | same derive-from-content mechanism |
| `BundleRequest` | needs parameterization (`ClaimsRequest` projection) |
| `resource_seeds` | one `EnvironmentResourceSeed` per resource (`payer`, `claim`, `policy`, `clinical_note`, `appeal`) |
| `dependency_fixtures` | reuse; recorded payloads for `policy.retrieval` and `appeal.submission` |
| `fault_script` | reuse; inject `timeout` at the `policy.retrieval` boundary |
| `review`, `redaction_decisions`, `coverage` | reuse unchanged |

## 7. Scenarios in the fixture module

| Scenario | Category | Behavior the lab must reproduce |
| --- | --- | --- |
| `ref-claims-01-stale-policy` | retrieval_failure | stale policy must block appeal drafting and escalate; never cite the wrong version |
| `ref-claims-02-auto-submit-threshold` | policy_failure | score 0.72 below the 0.8 threshold and no confirmation: submission blocked under both autonomy variants |
| `ref-claims-03-policy-timeout` | infrastructure_failure | one timeout, retry succeeds, draft grounded in the current policy; submission still requires confirmation |

## 8. Boundaries

- The agent drafts and submits appeals only against the retrieved policy
  version; an ungrounded appeal is a blocked turn, never a submission.
- The success score is a decision recorded in the trace (`policy_decisions`),
  not a hidden model output; the threshold gate is enforced in code.
- Payer submission and provider contact are recorded fixtures or strict
  simulators, never real external effects.
- One agent per denial; no multi-agent graph.
- Fully offline-runnable: `uv run python -c "import app.domain.reference_workflows.claims_denial.fixtures"`.
