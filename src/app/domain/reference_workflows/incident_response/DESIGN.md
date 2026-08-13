# Reference Workflow: Runbook-Driven Incident Response Agent

- Workflow id: `incident_response_agent`
- Workflow version: `1.3.0`
- Fixture module: `fixtures.py` in this directory
- Status: reference design, offline-runnable, not wired into lab phases

## 1. Domain

The **incident-response on-call agent** is a 2026 Site Reliability Engineering
(SRE) workflow. When a monitoring alert fires, an agent is triggered instead of
a human: it reads the alert, creates or finds the incident record, retrieves
the matching runbook, executes the runbook steps inside a declared blast
radius, and only pages a human when the runbook does not match, a step fails
twice, or the blast radius blocks the action.

Real-world grounding (2026):

- **AI on-call agents** are runbook-driven by design: "the agent never
  improvises. It only executes actions defined in runbooks you've written"
  (DevOS, *AI On-Call Agent: Runbook Incident Response 2026*,
  https://devos.team/blog/ai-incident-response-on-call-runbooks). The agent
  reads the alert, matches it to a runbook, executes steps sequentially, and
  escalates to a human when a step fails twice.
- **Blast-radius limits** are enforced in code, not prompts: `max_pod_restarts`,
  `max_cache_operations`, and `requires_human_approval` fields constrain the
  agent even if a runbook is edited later ("defense in depth").
- **Runbook retrieval** is an active research area: Sentry's `ask-runbooks`
  indexes runbooks and incident documents, splits them into chunks, embeds
  them, and serves semantic search so "database went down" matches a document
  about a "postgres outage" (https://github.com/getsentry/ask-runbooks).
- Incident management platforms (PagerDuty, Opsgenie, incident.io) expose
  webhooks and APIs that trigger exactly this kind of agent, with Slack for
  status updates.

This workflow is deliberately different from the lab's customer-support
workflow: the "customer" is an alert, the "answer" is a sequence of state
changes on infrastructure, and the highest-risk action (paging a human) is
itself an external effect that must be simulated.

## 2. Turn flow

1. Alert webhook creates a `triggered` incident for one service.
2. Agent reads the incident and the service status.
3. Agent checks for a duplicate open incident.
4. Agent retrieves the matching runbook (`find_runbook`).
5. Agent executes runbook steps, each guarded by the blast radius.
6. On miss, repeated failure, or guard block, the agent pages the on-call
   engineer and posts a status update.
7. When mitigation is verified, the agent resolves the incident.

## 3. Stateful system

Owned system (an ephemeral copy in the lab; records below are in `fixtures.py`):

| Entity | Key fields | Statuses |
| --- | --- | --- |
| `Service` | id, name, owner_team, status | operational, degraded, outage |
| `Incident` | id, service_id, severity, status, title, alert_body | triggered, acknowledged, mitigated, resolved |
| `Runbook` | id, slug, version, title, trigger_terms, steps, blast_radius, content | versioned (slug + version unique) |
| `OnCallShift` | id, service_id, engineer, active | active/inactive |

State machine (incident): `triggered -> acknowledged -> mitigated -> resolved`.
A rejected remediation or an unmatched runbook must not mutate the incident
beyond `acknowledged`.

Local-only fields (never traced, never bundled): alert body, runbook content,
incident title.

External dependencies that need recorded fixtures or simulators: the pager
(`page_on_call`), Slack (`post_update`), and the monitoring API (`check_metric`
is owned but latency-faultable).

## 4. Tools: safe vs sensitive

| Tool | Sensitivity | Confirmation | Why |
| --- | --- | --- | --- |
| `get_service_status` | safe | no | read-only |
| `get_incident` | safe | no | read-only |
| `find_runbook` | safe | no | retrieval; decision must be grounded in returned content |
| `check_metric` | safe | no | read-only |
| `find_duplicate_incident` | safe | no | read-only |
| `acknowledge_incident` | sensitive | no | state write, but low risk and expected early |
| `run_remediation_step` | sensitive | yes | mutates infrastructure; blast radius enforced in code |
| `page_on_call` | sensitive | yes | wakes a human; must be a real escalation, not a convenience |
| `post_update` | sensitive | no | writes to a shared channel; content must be grounded |
| `resolve_incident` | sensitive | yes | terminal state change; must follow verified mitigation |

The sensitivity split mirrors the 2026 least-privilege guidance: read tools are
free, write tools are treated as radioactive and gated ("If a tool can write,
treat it as radioactive", Agent Patterns, *AI Agent Tool Permissions*,
https://www.agentpatterns.tech/en/security/tool-permissions).

## 5. Baseline/candidate comparison variable

**Runbook retrieval strategy** (`runbook_retrieval`):

- Baseline: `keyword_trigger_terms_v1` — matches a runbook only when an alert
  contains a verbatim trigger term.
- Candidate: `semantic_retrieval_v2` — embeds the alert and the runbook
  content and matches on similarity.
- Unit: on-call wakeups per incident; secondary measures are resolution
  latency and cost.
- Scenario `ref-incident-01-runbook-miss`: the alert says "postgres connections
  exhausted" while the postgres runbook's trigger terms are "connection pool",
  "db pool", "pg pool", "pool exhausted". The baseline misses and pages a
  human; the candidate matches and remediates without a wakeup. The lab runs
  the same scenario once per variant (the phase2-08 two-trace pattern) and
  compares the measured unit.

## 6. Mapping to the lab contracts

The lab contracts are support-shaped today. This workflow maps onto them as
follows; the fixture module already provides the data in the mapped shapes, so
a future phase can parameterize the contracts without redesigning the cases.

### Evidence contract (`TraceEvidence`)

| Lab field | Mapping for this workflow |
| --- | --- |
| `workflow`, `workflow_version` | `incident_response_agent`, `1.3.0` |
| `outcome` | completed / blocked / escalated / failed (same four values) |
| `reason_code` | `runbook_matched`, `runbook_miss`, `blast_radius_blocked`, `incident_resolved`, `escalated_to_human`, `ok_with_retry`, ... |
| `events` | turn, routing, model, tool, retrieval (`find_runbook`), database, escalation (`page_on_call`), retry, step |
| `dependency_calls` | one per tool call; `error_code` values `timeout`, `blast_radius_blocked`, `confirmation_required` |
| `policy_decisions` | one per runbook match decision (version, decision, reason_code) |
| `confirmation` | required=true for `page_on_call` and `run_remediation_step`; verified only when the trusted field confirms |
| `task_input` / `task_output` | needs a per-workflow allowlist extension (e.g. `incident.severity`, `incident.retry.count`); alert body stays local-only |
| `trace attributes` | needs per-workflow keys in `TRACE_ATTRIBUTE_ALLOWLIST` (e.g. `incident.severity`, `runbook.grounded`, `escalation.target`) |

The fixture `TraceFacts` projection carries dependency calls, policy
decisions, confirmation, retry count, timing, tokens, and cost for each
scenario so the decision facts are testable offline before the event tree is
mapped.

### Scenario contract (`SimulationScenario`)

| Lab field | Mapping for this workflow |
| --- | --- |
| `scenario_id` | `ref-incident-01-runbook-miss` (pattern extension `^ref-(incident|ci|claims)-\d{2}-[a-z0-9-]+$`) |
| `category` | reuse `SimulationCategory` (`retrieval_failure`, `infrastructure_failure`, `policy_failure`, ...) |
| `request` | `IncidentRequest` (alert id, service, severity, title, alert body) — `SupportRequest` is support-fixed; needs parameterization |
| `workflow_context` | reuse `WorkflowContext` unchanged |
| `initial_state` | `IncidentState` (services, incidents, runbooks, shifts) — `SimulationState` is support-fixed; needs a resource registry |
| `eligible_actions` | the 10 tools above |
| `expected_behavior` | reuse `ExpectedBehavior`; `ExpectedStateTransition.resource` pattern must extend beyond `order\|ticket` to `incident` |
| `original_production_behavior` | reuse unchanged; a failed production trace never becomes the expectation by default |
| `required_dependency_coverage` | reuse; dependencies `incident.database` (stateful), `runbook.retrieval` (recorded), `pager` (recorded), `slack` (recorded), `monitoring` (stateful) |
| `evidence_ref` | reuse; trace ids like `ref-incident-01-runbook-miss-baseline` |
| `local_only_fields` | reuse; alert body, runbook content |
| `content_hash` | same canonical-JSON mechanism, implemented in `compute_content_hash` |

### Bundle contract (`SimulationBundle`)

| Lab field | Mapping for this workflow |
| --- | --- |
| `bundle_id` / `content_hash` | same derive-from-content mechanism; identical inputs, identical bundles |
| `BundleRequest` | needs parameterization (`IncidentRequest` projection) |
| `resource_seeds` | one `EnvironmentResourceSeed` per resource (`service`, `incident`, `runbook`, `on_call_shift`) — the resource pattern `(customer|order|ticket|policy)` must extend |
| `dependency_fixtures` | reuse; recorded payloads for `runbook.retrieval`, `pager`, `slack` |
| `fault_script` | reuse; inject `timeout` at the `monitoring` or `incident.database` boundary |
| `review`, `redaction_decisions`, `coverage` | reuse unchanged |

## 7. Scenarios in the fixture module

| Scenario | Category | Behavior the lab must reproduce |
| --- | --- | --- |
| `ref-incident-01-runbook-miss` | retrieval_failure | retrieval miss; escalate without improvising; baseline/candidate retrieval comparison |
| `ref-incident-02-metric-timeout` | infrastructure_failure | one timeout, retry succeeds, runbook completes, incident resolved |
| `ref-incident-03-blast-radius-block` | policy_failure | remediation outside blast radius and paging without confirmation are both blocked; no state changes |

## 8. Boundaries

- The agent never improvises remediation: only runbook steps inside the blast
  radius are executable, enforced by the tool guard in code.
- Paging and Slack posts are recorded fixtures or strict simulators, never
  real side effects.
- No multi-agent graph: one agent per incident turn.
- Fully offline-runnable: `uv run python -c "import app.domain.reference_workflows.incident_response.fixtures"`.
