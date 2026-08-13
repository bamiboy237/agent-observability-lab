# Reference Workflow: E-Commerce Returns Resolution Agent

**Status:** Proposed reference workflow (fixture data ready, no lab code changed)
**Date:** August 12, 2026
**Fixture module:** `src/app/domain/reference_workflows/returns_resolution.py`

## 1. Domain and purpose

The workflow is an **e-commerce returns resolution agent**. It is the first
line of defense for customer returns, refunds, and exchanges after an order
is delivered. The agent reads a return request, verifies who owns the order,
checks the current return policy, decides eligibility, and either approves
the return (label + refund or store credit) or denies or escalates it.

This is a 2026 production reality, not a hypothetical:

- Sagepilot's 2026-07 guide describes agents that run the whole return flow:
  eligibility checks, return labels, refunds, exchange steering, and
  "where is my refund" (WISMO) status answers, with escalation only when
  policy or judgment requires a person. Narvar data in the same article
  reports roughly 60% of consumers accept an exchange or store credit when
  the process is quick.
- AgentKits' 2026-05 "Refund & Returns Resolution Agent" blueprint defines
  the exact control loop this fixture models: `get_request`, `verify_order`,
  `check_policy`, `check_eligibility`, `process_refund` (hard-capped),
  `detect_abuse`, `escalate`, `log_decision`. Its core design rule: the
  worst-case action is an incorrect refund decision, so the agent never
  moves money beyond a hard cap and anything over cap, out of window,
  disputed, or suspicious goes to a person.

Sources: https://www.sagepilot.ai/blog/ai-agents-ecommerce-returns-refunds-exchanges-automation
(2026-07-20); https://www.agent-kits.com/blog/build-refund-returns-agent
(2026-05-30).

## 2. Stateful system

The agent reads and mutates a disposable returns database. It also calls two
external systems that the lab must simulate because real calls would move
money or ship goods:

| Entity | Key fields | Statuses |
|---|---|---|
| `Customer` | id, name, email | — |
| `Order` | id, customer_id, item_category, total_amount, delivered_at | `delivered`, `returned` |
| `ReturnRequest` | id, customer_id, order_id, reason_code, requested_refund_amount | `submitted`, `approved`, `label_issued`, `refund_pending`, `refunded`, `exchanged`, `denied`, `escalated` |
| `RefundProposal` | proposal_id, return_request_id, amount, policy_version | `proposed`, `confirmed`, `executed`, `blocked` |
| `ReturnPolicyDocument` | slug, version, title, content, content_hash | versioned; newest is truth |

Canonical transitions (approved set; anything outside is an unexpected
state change):

```text
return_request: submitted -> approved -> label_issued -> refund_pending -> refunded
                                                              \-> exchanged
                  submitted -> denied | escalated
order: delivered -> returned          (after restock)
refund_proposal: proposed -> confirmed -> executed
                  proposed -> blocked
```

The refund cap is a contract-level constant: `REFUND_CAP_USD = 500.00`. The
model cannot talk the tool into a larger refund.

## 3. Tools: safe vs sensitive

**Safe (read-only; no side effects):**

| Tool | Purpose |
|---|---|
| `get_order` | Read one order by id |
| `verify_order_ownership` | Confirm the requester owns the order |
| `get_return_policy` | Retrieve the live policy document by slug |
| `check_return_eligibility` | Evaluate window, condition, and proof against policy |
| `get_return_status` | Answer WISMO questions from live state |
| `detect_abuse` | Read the abuse-risk score for the requester/order |

**Sensitive (write or external effect):**

| Tool | Effect | Guardrail |
|---|---|---|
| `approve_return` | State change: `submitted -> approved` | After ownership + eligibility pass |
| `issue_return_label` | External shipping API call (carrier label) | Recorded adapter; only after approval |
| `process_refund` | Moves money in the payment system | Hard cap 500 USD; confirmation gate (see section 4) |
| `issue_store_credit` | Creates store credit | Alternative offered to the customer |
| `escalate_to_human` | Creates a support ticket | Over-cap, out-of-window, ownership mismatch, abuse |
| `log_decision` | Audit record of every decision | Always; immutable |

Ordering rule (from the AgentKits blueprint): verify ownership **before**
revealing order details or approving anything. A mismatch is a full stop.

## 4. Baseline/candidate comparison variable (exactly one)

**Variable:** `refund_confirmation_gate`

| | Behavior |
|---|---|
| **Baseline** | `process_refund` executes as soon as eligibility passes and the amount is at or under the cap (auto-refund in one turn). |
| **Candidate** | `process_refund` requires an explicit customer confirmation turn. The agent proposes the amount, the customer confirms, then the refund executes. An unconfirmed proposal blocks. |

Everything else stays fixed: same state, same tools, same prompts except the
one confirmation rule, same model, same budgets.

Expected measurable difference: the baseline resolves eligible returns in
fewer turns and less latency, but refunds before the item is scanned at the
carrier (fraud/abuse exposure). The candidate adds one turn and one model
call (latency and cost) and blocks refunds on unconfirmed proposals.

## 5. Mapping to existing lab contracts

The lab contracts are support-domain-specific in places. This section states
exactly how the returns workflow maps onto each, and what a future phase must
generalize. **No existing code changes; this is the mapping design only.**

### Evidence contract (`TraceEvidence`, `app.domain.evidence.schemas`)

- **Source:** one production returns trace from LangSmith/Braintrust: the
  normalized `TraceSourceRef` (platform, project, trace_id, url).
- **Event kinds:** reuse `turn`, `routing`, `answer`, `model`, `tool`,
  `retrieval`, `database`, `policy`, `confirmation`, `escalation`, `retry`,
  `step` unchanged. A refund confirmation maps to `confirmation`, policy
  retrieval maps to `policy`, `process_refund` maps to `tool`, order reads
  map to `database`.
- **Outcomes:** reuse `completed`, `blocked`, `escalated`, `failed`.
  Baseline auto-refund on the confirmation-gate scenario records
  `completed`; the candidate records `blocked` with reason
  `return_blocked_unconfirmed`.
- **Attributes:** the current `TASK_INPUT_ALLOWLIST` /
  `TASK_OUTPUT_ALLOWLIST` in `app.telemetry.allowlist` are support-specific
  (`support.intent`, `support.outcome`). The returns workflow maps to the
  same shapes but needs a per-domain prefix (for example `returns.outcome`,
  `returns.reason.code`, `returns.policy.grounded`, `returns.retry.count`).
  Adding those names to the allowlist is a future, separate change.

### Scenario contract (`SimulationScenario`, `app.domain.simulation.schemas`)

- **request:** the current `SupportRequest` (customer_id, message,
  refund_confirmed) maps 1:1 to the returns request: actor id, the customer
  message, and the trusted `refund_confirmed` flag. The confirmation gate
  reuses the lab's "the model cannot set the confirmation flag" rule.
- **initial_state / SimulationState:** today the state holds
  `orders`, `tickets`, `policies`. Returns state adds `return_requests` and
  `refund_proposals`; `orders` and `policies` already exist. `tickets` is
  unused (escalations create tickets only under `escalate_to_human`).
- **eligible_actions:** the returns tool list above; `TOOLS_BY_INTENT` is
  support-specific and a returns intent map is the equivalent extension.
- **expected_behavior:** `ExpectedBehavior.outcome`, `reason_codes`,
  `policy_grounded`, `policy_version`, `budgets` apply unchanged.
  `ExpectedStateTransition.resource` currently allows only `order|ticket`;
  the returns workflow needs `return_request` and `refund_proposal` added
  to that pattern, plus `any_resource_id` for newly created return requests.
- **dependency coverage:** `DependencyCoverageRequirement` applies
  unchanged: `returns.database` (stateful), `shipping.label` (recorded),
  `payments.refund` (recorded), `policy.retrieval` (recorded).

### Bundle contract (`SimulationBundle`, `app.domain.bundle.schemas`)

- **resource seeds:** `EnvironmentResourceSeed.resource` currently allows
  `customer|order|ticket|policy`. Returns adds `return_request` and
  `refund_proposal`; `validate_resource_seed` in
  `app.domain.bundle.allowlist` gains the matching record validators.
- **dependency fixtures:** `DependencyFixture` applies unchanged. The
  payment and shipping adapters replay approved fixture payloads
  (`payments.refund`, `shipping.label`); the recorded adapter's
  exact-match rule already covers the `arguments` normalization.
- **fault scripts:** a scripted `payments.refund` timeout or malformed
  response reproduces the lab's existing fault categories for the returns
  domain.
- **redaction and review:** `RedactionDecision` and `ReviewDecision`
  (approved-only) apply unchanged; the reviewer approves the expected
  behavior, never a failed production output.

## 6. Fixture module

`src/app/domain/reference_workflows/returns_resolution.py` is
self-contained: stdlib only, no database, no network, no `app.*` imports.
It provides:

- stable UUIDs (`uuid5` over `SEED_NAMESPACE`);
- two versioned `ReturnPolicyDocument` records (current 2026-07-30 with a
  14-day window and 500 USD cap; stale 2026-01-01 with a 30-day window and
  1000 USD cap), each with a sha256 content hash;
- customers, delivered orders, return requests, and the refund cap;
- `SAFE_TOOLS`, `SENSITIVE_TOOLS`, `STATE_TRANSITIONS`;
- the `CONFIRMATION_GATE` comparison variable (baseline/candidate);
- three `WorkflowScenario` sketches with canonical-JSON content hashes:
  `returns-01-refund-before-return`, `returns-02-stale-return-window`,
  `returns-03-ownership-mismatch`.

Determinism: identical imports produce identical UUIDs, hashes, and
scenario content hashes. A unit test asserts this.

## 7. Scope boundaries

Not included (bounded by design): real payment or shipping calls, inventory
restock, exchange inventory matching, abuse model training data, and the
multi-turn conversation UI. These are external effects the lab records or
simulates, never executes.
