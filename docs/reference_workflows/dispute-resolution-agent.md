# Reference Workflow: Banking Dispute Resolution Agent

**Status:** Proposed reference workflow (fixture data ready, no lab code changed)
**Date:** August 12, 2026
**Fixture module:** `src/app/domain/reference_workflows/disputes.py`

## 1. Domain and purpose

The workflow is a **banking dispute resolution agent**. It handles a
customer's disputed transaction from intake to outcome: classify the claim
(unauthorized, merchant error, processing failure, friendly fraud), gather
evidence from several systems, apply the Reg E / PSD2 style timeline,
recommend or issue provisional credit, and escalate when the case needs a
human reviewer. It exists because manual dispute handling spans five to
eight systems and twelve to forty steps, with resolution timelines of 30 to
120+ days, while Regulation E in the US requires acknowledgment within five
business days and PSD2 in Europe requires refunding unauthorized
transactions within one business day.

This is a 2026 production reality, not a hypothetical: Backbase's 2026-05
agentic dispute-resolution analysis describes the five-stage pipeline
(intake/classification, automated evidence gathering, predictive resolution
and decision authority, regulatory compliance, customer notification), notes
that 70-80% of decisions are deterministic once evidence is complete, and
reports fraud losses of $33.83B globally in 2023 with US losses projected
near $40B by 2027. McKinsey's banking analysis (cited there) shows
multi-agent evidence gathering outperforming single-system automation on
exception-heavy workflows like disputes.

Sources: https://www.backbase.com/blog/agentic-ai-banking-dispute-resolution
(2026-05-26); https://www.backbase.com/blog/ai-banking-dispute-resolution-automation
(2026-05-26).

## 2. Stateful system

The agent reads and mutates a disposable banking database (ledger, accounts,
cases). Fraud signals and authentication events come from external systems
that the lab records or simulates.

| Entity | Key fields | Statuses |
|---|---|---|
| `Customer` | id, name, email | — |
| `Account` | id, customer_id, status | `active`, `frozen` |
| `Transaction` | id, account_id, merchant, amount, posted_at, auth_method | — |
| `FraudSignal` | transaction_id, signal_name, score, source | — (external, recorded) |
| `DisputeCase` | account_id, transaction_id, category, evidence_sources, reg_e_ack_deadline, ack_sent_at | `intake`, `evidence_gathering`, `decision_pending`, `provisional_credit_issued`, `resolved`, `denied`, `escalated` |
| `RegulationDocument` | slug, version, content, content_hash | versioned; newest is truth |

Canonical transitions (approved set):

```text
dispute_case: intake -> evidence_gathering -> decision_pending -> provisional_credit_issued -> resolved
                                                        \-> denied
              evidence_gathering -> escalated
```

Timeline rules (regulation version 2026-06-01): acknowledge within 5
business days; provisional credit within 1 business day after
acknowledgment for unauthorized claims unless fraud signals indicate
cardholder involvement; final resolution within 45 days; at least three
evidence sources before a final decision; missed timelines force escalation.

## 3. Tools: safe vs sensitive

**Safe (read-only):**

| Tool | Purpose |
|---|---|
| `get_account` | Read the account and its status |
| `get_transaction` | Read the disputed transaction record |
| `get_fraud_signals` | Read fraud-model outputs (recorded external system) |
| `get_auth_events` | Read authentication/device events (recorded external system) |
| `get_dispute_timeline_regulation` | Retrieve the live regulation document |
| `get_case_status` | Report case progress and deadlines |

**Sensitive (write or external effect):**

| Tool | Effect | Guardrail |
|---|---|---|
| `acknowledge_dispute` | Records the Reg E acknowledgment timestamp | Must run within 5 business days of intake |
| `open_dispute_case` | Creates a case in `intake` | After classification |
| `issue_provisional_credit` | Credits the account (money movement) | Only after acknowledgment; blocked when fraud signals indicate cardholder involvement or evidence is incomplete |
| `deny_dispute` | Closes the case as denied | Only after evidence review; reasons recorded |
| `file_regulatory_notice` | External regulatory filing | Recorded adapter; only on resolution or escalation |
| `escalate_to_reviewer` | Hands the case to a human reviewer | Timeline risk, friendly-fraud suspicion, incomplete evidence |

Ordering rule: classify, acknowledge, gather at least three evidence
sources, then decide. Money moves only through `issue_provisional_credit`
with its guardrails; the model cannot credit directly.

## 4. Baseline/candidate comparison variable (exactly one)

**Variable:** `evidence_source_minimum`

| | Behavior |
|---|---|
| **Baseline** | The agent recommends a decision after one evidence source (the ledger transaction record). |
| **Candidate** | The agent gathers at least three evidence sources (transaction record, fraud signals, authentication events) before recommending a decision. |

Everything else stays fixed: same state, same tools, same model, same
prompts except the evidence-completeness rule.

Expected measurable difference: on `disputes-01-credit-on-single-source` the
baseline issues provisional credit immediately after acknowledgment; the
candidate blocks the credit until the fraud-signal and auth-event sources
arrive. On `disputes-03-friendly-fraud-credited` the candidate's third
source (fraud signals) reclassifies a cardholder-present charge and denies
it, where the baseline would credit it. The variable is a retrieval change
(more sources), which the lab's single-variable rule supports.

## 5. Mapping to existing lab contracts

### Evidence contract (`TraceEvidence`, `app.domain.evidence.schemas`)

- **Source:** one production dispute trace (LangSmith/Braintrust) via
  `TraceSourceRef`.
- **Event kinds:** reuse `turn`, `routing`, `answer`, `model`, `tool`,
  `retrieval`, `database`, `policy`, `confirmation`, `escalation`, `retry`,
  `step`. Fraud-signal and auth-event fetches map to `retrieval`; the
  regulation fetch maps to `policy`; acknowledgment and credit map to
  `confirmation` / `tool`.
- **Outcomes:** reuse `completed`, `blocked`, `escalated`, `failed`.
- **Attributes:** same allowlist note as the other workflows: the disputes
  workflow needs a `disputes.*` attribute prefix
  (`disputes.outcome`, `disputes.reason.code`, `disputes.policy.grounded`,
  `disputes.retry.count`) added to `app.telemetry.allowlist` in a future,
  separate change. `agent.workflow.version` applies unchanged.

### Scenario contract (`SimulationScenario`, `app.domain.simulation.schemas`)

- **request:** `SupportRequest` maps to the dispute request: actor id (the
  customer), the natural-language claim, and `refund_confirmed` maps to the
  trusted "customer confirms the charge is unauthorized" flag.
- **initial_state / SimulationState:** dispute state adds `accounts`,
  `transactions`, `fraud_signals`, `cases` alongside `policies` and the
  existing slots.
- **eligible_actions:** the dispute tool list above; a new intent map
  mirrors `TOOLS_BY_INTENT`.
- **expected_behavior:** `outcome`, `reason_codes`, `policy_grounded`,
  `policy_version`, `budgets` apply unchanged.
  `ExpectedStateTransition.resource` needs `dispute_case` (and optionally
  `account`) added to its pattern; `any_resource_id` covers newly opened
  dispute cases.
- **dependency coverage:** `banking.database` (stateful),
  `fraud.signals` (recorded), `auth.events` (recorded), `clock` (recorded —
  the lab already simulates time for deadline scenarios).

### Bundle contract (`SimulationBundle`, `app.domain.bundle.schemas`)

- **resource seeds:** `EnvironmentResourceSeed.resource` gains `account`,
  `transaction`, `fraud_signal`, `dispute_case`; `validate_resource_seed`
  gains the matching validators.
- **dependency fixtures:** `DependencyFixture` applies unchanged for
  recorded fraud-signal, auth-event, regulatory-filing, and clock
  responses. Exact-match argument rules apply as today.
- **fault scripts:** a scripted `fraud.signals` timeout reproduces the
  incomplete-evidence case; a scripted clock freeze reproduces the Reg E
  acknowledgment-timeout case.
- **redaction and review:** unchanged; the reviewer approves the expected
  outcome, and the bundle never contains real account numbers or customer
  identity data.

## 6. Fixture module

`src/app/domain/reference_workflows/disputes.py` is self-contained:
stdlib only, no database, no network, no `app.*` imports. It provides:

- stable UUIDs (`uuid5` over `SEED_NAMESPACE`);
- two versioned `RegulationDocument` records (current 2026-06-01 with the
  5-day acknowledgment and 3-source evidence rules; previous 2026-01-01
  with a 10-day acknowledgment and single-source rule), each with a sha256
  content hash;
- a customer, an account, two transactions (card-not-present and
  chip-and-PIN), two fraud signals with scores, and two dispute cases with
  Reg E deadlines;
- `SAFE_TOOLS`, `SENSITIVE_TOOLS`, `STATE_TRANSITIONS`;
- the `EVIDENCE_COMPLETENESS` comparison variable (baseline/candidate);
- three `WorkflowScenario` sketches with canonical-JSON content hashes:
  `disputes-01-credit-on-single-source`,
  `disputes-02-reg-e-ack-timeout`,
  `disputes-03-friendly-fraud-credited`.

Determinism: identical imports produce identical UUIDs, hashes, and
scenario content hashes. A unit test asserts this.

## 7. Scope boundaries

Not included (bounded by design): real payment rails, real fraud-model
serving, real regulatory filings, merchant documentation requests, and
customer notifications beyond the acknowledgment. These are recorded or
simulated in the lab.
