# Reference Workflow: HR Onboarding Coordinator Agent

**Status:** Proposed reference workflow (fixture data ready, no lab code changed)
**Date:** August 12, 2026
**Fixture module:** `src/app/domain/reference_workflows/onboarding.py`

## 1. Domain and purpose

The workflow is an **HR onboarding coordinator agent**. It turns a hired
candidate into an active employee record with a complete, compliant
onboarding checklist, ready for the first pay cycle. The agent drafts worker
records, selects role- and location-appropriate checklists, tracks compliance
tasks (identity verification, background check, payroll enrollment, IT
provisioning, location-specific E-Verify cases), and hands the record to an
HR manager for confirmation before activation.

This is a 2026 production reality, not a hypothetical: Microsoft's
**Onboarding Agent in Dynamics 365 Human Resources** (public preview, 2026)
runs inside Microsoft Teams, writes onboarding actions back to the HR system
of record, drafts worker records, assigns positions, and recommends
checklists and leave plans that HR managers review and confirm instead of
retyping. Compensation flows downstream to Finance, so payroll readiness is
an explicit success criterion.

Sources: https://www.microsoft.com/en-us/dynamics-365/blog/it-professional/2026/06/30/onboarding-agent-dynamics-365-human-resources/
(2026-06-30).

## 2. Stateful system

The agent reads and mutates a disposable onboarding database. External
systems (compliance E-Verify, payroll, IT provisioning) are recorded or
simulated because real calls create legal records and provision access.

| Entity | Key fields | Statuses |
|---|---|---|
| `Candidate` | id, name, email, work_authorization_verified | — |
| `Position` | id, title, department, location, compensation_tier | — |
| `WorkerRecord` | id, candidate_id, position_id, compensation_tier, start_date | `draft`, `pending_review`, `active` |
| `ChecklistTemplate` | slug, version, title, tasks, content_hash | versioned; generic vs location-specific |
| `OnboardingTask` | worker_record_id, template_slug, task_name | `pending`, `in_progress`, `completed`, `waived`; `required_for_payroll` flag |
| `OnboardingCase` | candidate_id, position_id, start_date | `intake`, `drafting`, `awaiting_review`, `active`, `blocked` |
| `OnboardingPolicyDocument` | slug, version, content, content_hash | versioned; newest is truth |

Canonical transitions (approved set):

```text
onboarding_case: intake -> drafting -> awaiting_review -> active
                                      \-> blocked
worker_record: draft -> pending_review -> active
onboarding_task: pending -> completed | waived
```

The compliance policy (version 2026-08-01) makes every task required before
the first pay cycle and adds an E-Verify case for E-Verify locations.

## 3. Tools: safe vs sensitive

**Safe (read-only):**

| Tool | Purpose |
|---|---|
| `get_candidate` | Read the hired candidate and authorization status |
| `get_position` | Read the position, location, and compensation tier |
| `get_worker_record` | Read the worker record state |
| `get_checklist_template` | Retrieve a checklist template by slug/version |
| `get_onboarding_policy` | Retrieve the live compliance policy |
| `get_case_status` | Report case progress |

**Sensitive (write or external effect):**

| Tool | Effect | Guardrail |
|---|---|---|
| `draft_worker_record` | Creates a record in `draft` state | Never created `active` directly |
| `activate_worker_record` | `pending_review -> active` | Only after HR confirmation of position, tier, start date |
| `assign_position` | Binds candidate to position | Must match the approved offer |
| `select_checklist` | Attaches a checklist template | Must cover all policy-required tasks for role + location |
| `complete_task` | Marks a task completed | Only when the underlying record exists (I-9, E-Verify, payroll, IT) |
| `request_everify_case` | External compliance system call | Recorded adapter; location-gated |
| `escalate_to_hr` | Creates an HR review case | Missing confirmation, missing records, ambiguity |

Ordering rule: draft first, confirm with HR second, activate last. Onboarding
closes only when every `required_for_payroll` task is completed.

## 4. Baseline/candidate comparison variable (exactly one)

**Variable:** `checklist_selection_source`

| | Behavior |
|---|---|
| **Baseline** | The agent applies the single generic checklist template to every new hire, regardless of role or location. |
| **Candidate** | The agent selects the role- and location-specific checklist template, which adds location compliance tasks (for example the Berlin template adds `everify_case`). |

Everything else stays fixed: same state, same tools, same model, same
prompts except the template-selection instruction.

Expected measurable difference: the baseline completes onboarding without
the E-Verify task, creating a compliance gap and a payroll/first-cycle risk;
the candidate covers the task and blocks completion until it is done. The
scenario `onboarding-01-missed-location-compliance` is the direct
baseline/candidate comparison.

## 5. Mapping to existing lab contracts

### Evidence contract (`TraceEvidence`, `app.domain.evidence.schemas`)

- **Source:** one production onboarding trace (LangSmith/Braintrust) via
  `TraceSourceRef`.
- **Event kinds:** reuse `turn`, `routing`, `answer`, `model`, `tool`,
  `retrieval`, `database`, `policy`, `confirmation`, `escalation`, `retry`,
  `step`. Checklist template lookup maps to `retrieval`; the compliance
  policy fetch maps to `policy`; record activation maps to `confirmation`
  because HR confirmation gates it; `complete_task` maps to `tool`.
- **Outcomes:** reuse `completed`, `blocked`, `escalated`, `failed`.
- **Attributes:** same allowlist note as the returns workflow: the
  onboarding workflow needs an `onboarding.*` attribute prefix
  (`onboarding.outcome`, `onboarding.reason.code`, `onboarding.policy.grounded`,
  `onboarding.retry.count`) added to `app.telemetry.allowlist` in a future,
  separate change. `agent.workflow.version` and the instruction version
  attributes apply unchanged.

### Scenario contract (`SimulationScenario`, `app.domain.simulation.schemas`)

- **request:** `SupportRequest` maps to the onboarding request: actor id
  (the HR manager or candidate), the natural-language request message, and
  `refund_confirmed` maps to the trusted "HR confirmation" flag that gates
  record activation. The model cannot set the flag.
- **initial_state / SimulationState:** onboarding state adds
  `candidates`, `positions`, `worker_records`, `checklist_templates`,
  `tasks`, `cases` alongside the existing `policies` slot.
- **eligible_actions:** the onboarding tool list above; a new intent map
  mirrors `TOOLS_BY_INTENT`.
- **expected_behavior:** `outcome`, `reason_codes`, `policy_grounded`,
  `policy_version`, `budgets` apply unchanged.
  `ExpectedStateTransition.resource` needs `onboarding_case`,
  `worker_record`, and `onboarding_task` added to its pattern for this
  domain; `any_resource_id` would cover newly drafted worker records.
- **dependency coverage:** `onboarding.database` (stateful),
  `compliance.everify` (recorded), `hr.payroll` (recorded),
  `it.provisioning` (recorded).

### Bundle contract (`SimulationBundle`, `app.domain.bundle.schemas`)

- **resource seeds:** `EnvironmentResourceSeed.resource` gains
  `candidate`, `position`, `worker_record`, `checklist_template`,
  `onboarding_task`, `onboarding_case`; `validate_resource_seed` gains the
  matching validators.
- **dependency fixtures:** `DependencyFixture` applies unchanged for the
  recorded E-Verify, payroll, and IT provisioning responses. Exact-match
  argument rules apply as today.
- **fault scripts:** scripted `compliance.everify` timeout reproduces a
  blocked case; scripted malformed payroll response reproduces the
  payroll-not-ready failure.
- **redaction and review:** unchanged; the reviewer approves the expected
  checklist coverage, never a failed production output.

## 6. Fixture module

`src/app/domain/reference_workflows/onboarding.py` is self-contained:
stdlib only, no database, no network, no `app.*` imports. It provides:

- stable UUIDs (`uuid5` over `SEED_NAMESPACE`);
- two versioned `OnboardingPolicyDocument` records (current 2026-08-01
  requiring location-specific tasks and draft-first records; previous
  2026-02-01 with a single standard checklist and direct activation), each
  with a sha256 content hash;
- candidates (one with work authorization verified, one without), positions
  (Berlin Engineering, Austin Design), generic and Berlin location checklist
  templates with content hashes, onboarding cases;
- `SAFE_TOOLS`, `SENSITIVE_TOOLS`, `STATE_TRANSITIONS`;
- the `CHECKLIST_SELECTION` comparison variable (baseline/candidate);
- three `WorkflowScenario` sketches with canonical-JSON content hashes:
  `onboarding-01-missed-location-compliance`,
  `onboarding-02-record-auto-activation`,
  `onboarding-03-payroll-not-ready`.

Determinism: identical imports produce identical UUIDs, hashes, and
scenario content hashes. A unit test asserts this.

## 7. Scope boundaries

Not included (bounded by design): real E-Verify or background-check calls,
real payroll feeds, real IT directory provisioning, offer-letter drafting,
and leave-plan personalization. These are recorded or simulated in the lab.
