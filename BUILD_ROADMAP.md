# Simulate — Authoritative Build Roadmap

Last updated: 2026-08-14

## Current state

- **Product:** Simulate
- **Promise:** Continuously evaluate and improve agentic workflows.
- **Completed:** Phases 0–7 are on `main` through merge commit `f31c438`.
- **Next:** Phase 8 is approved for planning. It is not implemented.
- **Source of truth:** This file owns product direction, phase scope, design rules,
  accepted decisions, and future work. Do not create a parallel strategy or
  roadmap document.

Simulate helps a company find important behavior in production agent traces,
turn that behavior into reviewed YAML scenarios, run controlled experiments in
isolated cloud environments, and inspect reproducible results. Simulate reports
evidence. It does not make the release decision.

## Product doctrine

1. **Study behavior, not only failures.** A successful refund can still be
   expensive, slow, or abnormal. Efficient successful behavior can also be
   worth preserving.
2. **Use production evidence to improve tests.** A trace is evidence. It is not
   automatically a safe scenario, correct business state, or expected result.
3. **Keep humans at the contract boundary.** Prime Agent can investigate,
   explain, and draft scenarios. A person must approve the YAML before Simulate
   publishes it or starts an experiment.
4. **Run controlled experiments.** Baseline and candidate runs use the same
   scenarios, starting state, fixtures, evaluators, and limits. Only declared
   candidate variables can differ.
5. **Measure stochastic systems as stochastic systems.** Repeat and interleave
   runs. Show averages, spread, and individual iterations.
6. **Return neutral evidence.** Report what changed and whether configured
   limits were met. Do not recommend a deployment or hide the underlying runs.
7. **Keep execution isolated and replaceable.** The control plane coordinates
   work. Ephemeral runners execute it on Lab infrastructure or customer BYOVM
   infrastructure.
8. **Prefer one mechanism.** Put workflow-specific data in versioned contracts.
   Do not create one execution path per workflow, provider, or interface.
9. **Make safety configurable where the customer owns the risk.** Preserve safe
   defaults, explicit contracts, audit records, short-lived credentials, and
   outbound allowlists.
10. **Build the core product first.** Do not add automatic deployment, broad
    autonomy, a second web product, or complex organization roles to the MVP.

## Core product loop

```text
opt-in production traces
  -> batch behavior discovery
  -> behavior report and insight inbox
  -> Prime Agent investigation and YAML drafts
  -> human review and approval
  -> versioned scenario or suite
  -> isolated repeated experiment
  -> neutral results and immutable evidence
  -> team decision
```

The loop supports two starting points:

- **Production discovery:** find behavior that changed or deserves review.
- **Planned change:** evaluate a prompt, model, tool, policy, retrieval, routing,
  or workflow-code change before release.

## Canonical language

Use these terms in product copy, code added from Phase 8 onward, APIs, and docs.
Do not rename stable code only for cosmetic consistency.

| Term | Meaning |
| --- | --- |
| **Workflow** | A registered agentic system with trace matching rules, source code, dependencies, limits, and sandbox settings. |
| **Behavior insight** | Evidence that a workflow behavior changed, violated a limit, or is worth preserving. It can contain successful and failed traces. |
| **Scenario** | A human-approved YAML contract for one controlled situation. |
| **Suite** | A saved set of versioned scenarios. |
| **Experiment** | A baseline and one or more candidate configurations run against approved scenarios. |
| **Iteration** | One execution of one configuration against one scenario. |
| **Result** | The immutable measurements and evidence from an experiment. |
| **Prime Agent** | The investigation agent that reviews an insight, drafts YAML and a developer message, and acts only within an explicit approval boundary. |
| **Runner** | An isolated process in an ephemeral VM that executes an experiment contract and uploads evidence. |
| **Control plane** | The hosted service that stores product objects and coordinates discovery, approval, and experiments. |
| **Execution plane** | Lab-managed or customer-managed compute that runs discovery jobs and experiments. |

Prefer **simulate** over **replay**. Use **reconstructed scenario** when a
scenario is based closely on a trace. Avoid **failure cluster** as the product
noun. Avoid **recommendation**, **ship**, and **do not ship** in result contracts.

## Product shape

### Users

Simulate serves three overlapping users:

- developers who change an agent workflow;
- reliability and evaluation engineers who define evidence and experiments;
- engineering leads who need to see material changes and their evidence.

All project members are administrators in the MVP. Only administrators can
approve and publish a scenario or approve an experiment. Add roles only after
real customer evidence shows that one role is unsafe or unusable.

### Object hierarchy

```text
Organization
  -> Project
    -> Workflow
      -> Insight
        -> Scenario or Suite
          -> Experiment
            -> Iteration
```

The hierarchy is for ownership and navigation. Provenance can cross it. For
example, one experiment can reference several insights, and one insight can
propose several scenarios.

### Core navigation

The product has four primary areas:

1. **Insights** — behavior discovery reports and the insight inbox.
2. **Scenarios** — reviewed YAML contracts and saved suites.
3. **Experiments** — running and completed comparisons.
4. **Admin** — workflows, trace sources, infrastructure, limits, data policy,
   destinations, and retention.

Do not add a primary navigation item until its backend behavior exists.

### Project home

The home view answers: **What are the three most important changes in agent
behavior since I last checked?**

It contains:

- **Needs attention:** at most three actionable insights;
- **Running:** active cloud experiments;
- **Recent evidence:** completed experiments and resolved insights;
- one-click access to all insights.

Each insight summary answers:

1. What changed?
2. Why does it matter?
3. What evidence supports it?
4. What can the user do next?

Do not show an unexplained AI score.

### Insight lifecycle

Use only these user-facing states:

- New
- Investigating
- Testing
- Resolved
- Dismissed

Draft generation and experiment execution are details within these states.
Dismissal requires a reason. The MVP does not train a model from dismissals or
human edits.

## Contracts and configuration

### Workflow registration

Each workflow has:

- stable identifier and display name;
- trace source and matching rules;
- source repository and entry point;
- declared tools and dependencies;
- configurable limits for outcomes, tool calls, retries, latency, tokens, and
  cost;
- sandbox, network, credentials, and data-handling settings;
- discovery schedule and minimum evidence settings;
- notification destinations.

The system must group traces within the declared workflow or task. Similar text
alone must not group unrelated domains.

### Scenario YAML

A published scenario records:

- schema version and stable scenario version;
- origin: `reconstructed`, `designed_variant`, `designed_edge_case`, or
  `benchmark`;
- source insight and trace references when applicable;
- sanitized initial state and user request;
- allowed dependencies and tools;
- recorded external responses or disposable service fixtures;
- expected outcome and evaluator definitions;
- allowed and forbidden state changes;
- tool-call, retry, latency, token, and cost limits;
- required approvals and cleanup behavior;
- workflow, prompt, model, tool, policy, fixture, and evaluator versions.

A trace-derived proposal starts from a central representative trace. Simulate
can add close variants and extremes, but must label each origin. Only the
human-edited, approved scenario becomes a persistent published version. The MVP
does not retain discarded generated drafts.

### Scenario storage

Storage is configurable per project:

- **Git mode:** Git is the source of truth. Simulate keeps an indexed copy.
- **Managed mode:** Simulate stores an immutable published version.

The MVP supports a guided form and a Prime Agent pull-request flow. Both produce
the same YAML contract and require explicit approval.

### Data policy

Projects choose one raw-trace policy:

- retain raw traces;
- retain only a sanitized projection;
- allow temporary access and retain no raw trace.

The safe default is temporary raw access plus sanitized retention. Replace
private values while preserving relations and behavior needed by the scenario.
Only configured sanitized insights, approved contracts, and allowlisted evidence
can leave customer infrastructure in BYOVM mode.

## System architecture

### Control plane

The hosted control plane stores organizations, projects, workflows, insights,
scenario metadata, experiments, results, audit records, configuration, and
runner leases. It exposes the API used by the CLI and Textual interface.

### Execution plane

Discovery and experiment work can run on:

- Lab-managed ephemeral VMs; or
- customer-provided VMs through BYOVM.

An experiment uses one clean ephemeral VM. The VM must be destroyed or cleaned
before a runner can accept new work. Each run uses approved synthetic or
sanitized state, short-lived experiment-scoped credentials, an explicit
outbound allowlist, and an immutable agent image.

### Runner protocol

1. The control plane creates an experiment and a signed lease.
2. A runner creates or claims a clean VM.
3. The runner verifies the experiment ID, lease expiry, image digest, scenario
   versions, and allowed dependencies.
4. The runner executes sequence-numbered iterations.
5. It buffers encrypted events during a short control-plane disconnect.
6. It resumes upload from the last acknowledged sequence without duplicates.
7. It uploads the immutable result and evidence.
8. It destroys the VM and invalidates the credentials.

A short connection loss does not stop a valid experiment. If the lease expires,
the runner stops, cleans up, discards the result, and reports an operational
failure after reconnect. The MVP does not publish partial experiment results.

### Remote access

Textual connects through the control-plane API. It does not connect directly to
the VM. A user can start a run through the API or CLI, disconnect SSH, reconnect,
and attach to the same experiment while the lease is valid. Plain JSON remains
the stable automation interface.

### Dependency policy

Each dependency selects an explicit mode:

- recorded fixture;
- disposable sandbox service;
- customer staging service;
- a customer-approved production service.

The scenario contract, network allowlist, credential scope, and cleanup policy
control access. Simulate must not silently choose a more permissive mode.

## Delivery rules

Each checkpoint must be reviewable by itself.

For every checkpoint:

1. define the user-visible behavior and contract;
2. add the smallest complete implementation;
3. add focused unit and integration checks;
4. run Ruff, mypy, and the relevant tests;
5. update this roadmap with evidence and limitations;
6. stop for review before the next checkpoint when the user requests
   checkpoint-gated delivery.

Do not claim remote, cloud, deterministic, safe, or durable behavior without a
focused test of the named boundary.

# Completed foundation

Phases 0–7 established the reference system and the first complete local
simulation path. Their code still contains older terms such as `failure`,
`regression`, and `comparison`. Phase 8 must migrate public product contracts
carefully. Do not perform a large mechanical rename.

## Phase 0 — Platform foundation [COMPLETE]

**Outcome:** FastAPI, typed settings, structured errors and logs, PostgreSQL,
Alembic, health checks, Docker, and CI provide one repeatable base.

**Primary evidence:** `src/app/config.py`, `src/app/db.py`, `src/app/main.py`,
`alembic/`, `docker-compose.yml`, `.github/workflows/ci.yml`, and platform tests.

## Phase 1 — Deterministic support reference system [COMPLETE]

**Outcome:** A deterministic support domain provides customers, orders,
policies, state transitions, stable errors, seed data, and HTTP boundaries.

**Primary evidence:** `src/app/domain/support/`, `src/app/api/support_router.py`,
and support integration tests.

## Phase 2 — Typed agent and privacy-safe tracing [COMPLETE]

**Outcome:** A typed Pydantic AI boundary can run scripted or hosted models and
records allowlisted agent, model, token, and tool evidence.

**Primary evidence:** `src/app/domain/agent/`, `src/app/adapters/`,
`src/app/telemetry/`, and agent/live-model tests.

## Phase 3 — Retrieval and grounding [COMPLETE]

**Outcome:** The reference workflow has versioned policy retrieval, hybrid
search, citations, retrieval metrics, and evaluation fixtures.

**Primary evidence:** `src/app/domain/retrieval/`,
`tests/fixtures/retrieval_eval_v1.jsonl`, and retrieval tests.

## Phase 4 — Controlled stateful workflow [COMPLETE]

**Outcome:** A LangGraph workflow persists checkpoints and requires explicit
human confirmation before controlled actions.

**Primary evidence:** `src/app/domain/workflow/`,
`src/app/api/workflow_router.py`, and checkpoint integration tests.

## Phase 5 — Canonical evidence and isolated simulation [COMPLETE]

**Outcome:** Provider adapters map traces into a canonical evidence contract.
The bundle compiler removes unsafe data, and the simulator runs against
recorded or isolated PostgreSQL dependencies.

**Primary evidence:** `src/app/domain/evidence/`, `src/app/domain/bundle/`,
`src/app/domain/simulation/`, LangSmith/Braintrust adapters, and evidence and
simulation tests.

## Phase 6 — Behavior grouping and review foundation [COMPLETE]

**Outcome:** The existing failure-oriented implementation imports feedback,
extracts deterministic features, groups related traces, stores review state,
and exposes review APIs. It proves the review mechanism, but its product model
is narrower than the approved behavior-insight model.

**Primary evidence:** `src/app/domain/failures/`,
`src/app/api/failures_router.py`, failure-review migrations and tests.

## Phase 7 — Scenarios, suites, simulator, and interfaces [COMPLETE]

**Outcome:** Reviewed evidence can become stored regression cases and suites.
The generic simulator runs YAML reference workflows through API, CLI, Rich, or
full-screen Textual views. The renderer consumes events and does not own
execution.

The local Textual workbench starts from bare `lab simulate`. It uses a guided
one-question setup, runs the same environment checks as direct CLI runs, and
shows a monochrome keyboard-first event and evidence workspace. Direct
`lab simulate run <scenario-id>` commands keep the Rich event stream.

**Primary evidence:** `src/app/domain/regression/`, `src/app/domain/suite/`,
`src/app/domain/user_simulator/`, `src/app/cli/simulate.py`,
`src/app/cli/textual_simulate.py`, `simulations/`, suite and simulator tests,
and `artifacts/audit/phase7-audit.*`.

**Completion evidence:** merged to `main` in `f31c438`; the merged validation
record reported 702 Docker tests, including 674 unit tests and 28 integration
tests.

# Phase 8 — Controlled experiment engine [NEXT — DO NOT BUILD YET]

## Outcome

Run a baseline and one or more candidate agent configurations across approved
scenarios in isolated cloud environments, repeat each scenario enough to
measure variability, and return reproducible evidence without making the
release decision.

The default experiment uses one selected scenario. A user can instead select
related scenarios or a saved suite.

## Phase 8.1 — Experiment contract and vocabulary

Define one versioned experiment contract with:

- one baseline and one or more candidates;
- baseline defaulting to the deployed configuration, with another saved version
  selectable;
- candidate changes declared as model, prompt, retrieval, tools, policy,
  routing, workflow code, or a combination;
- exact scenario versions and starting-state hashes;
- dependency, fixture, evaluator, and limit versions;
- repetition count, interleaving policy, concurrency, duration, and budget;
- a configurable ablation plan;
- trigger identity: a developer, PR or CI workflow, or Prime Agent after explicit
  approval;
- runner target: Lab-managed or BYOVM;
- retention and notification policy.

For a candidate with several declared changes, the default ablation plan runs
each change alone and then the full candidate. A project can configure another
plan.

**Acceptance:** invalid or undeclared differences fail before a VM starts. The
same contract can be submitted through Python, API, CLI, and Textual.

## Phase 8.2 — Immutable candidate and environment identity

- Accept either Git repository plus commit or an OCI image digest.
- If given Git identity, build the image and record its content digest.
- Record runtime, model, prompt, tool, policy, retrieval, fixture, scenario, and
  evaluator versions.
- Reject mutable image tags as the final executed identity.

**Acceptance:** a completed iteration can identify the exact code and data it
used without relying on the current repository state.

## Phase 8.3 — Cloud runner, lease, and reconnect protocol

- Implement one provider-neutral runner protocol.
- Support Lab-managed VMs and BYOVM without two experiment engines.
- Use signed, expiring, experiment-scoped leases and credentials.
- Sequence and acknowledge events. Buffer them locally in encrypted form during
  a bounded disconnect.
- Resume without duplicate events.
- Stop, clean up, and discard the result after lease expiry.
- Prove that a disconnected SSH or Textual client does not own execution.

**Acceptance:** kill and reconnect the client and control-plane connection in
focused tests. The experiment either reconnects safely or ends as a visible
operational failure with no partial result.

## Phase 8.4 — Isolated state and dependency modes

- Start each experiment from the approved synthetic or sanitized state.
- Capture all state changes as evidence.
- Enforce the scenario's tool, dependency, network, and credential contract.
- Support recorded, disposable sandbox, staging, and explicitly approved
  production dependency modes.
- Destroy or clean the VM before reuse.

**Acceptance:** tests prove isolation between experiments, outbound denial for
undeclared hosts, credential expiry, and cleanup after success, failure, and
cancellation.

## Phase 8.5 — Repeated and interleaved execution

- Repeat every baseline and candidate scenario a configurable number of times.
- Interleave baseline and candidate iterations to reduce time-order bias.
- Preserve each individual iteration.
- Apply the configured ablation plan.
- Enforce configurable maximum VMs, iterations, duration, and estimated model
  plus infrastructure cost.

**Acceptance:** execution order is reproducible from the contract, budget limits
stop new iterations, and every scheduled iteration has one final status.

## Phase 8.6 — Evaluation and statistics

Support both evaluator classes:

- deterministic YAML checks for outcomes, state changes, tool use, retries,
  errors, and declared limits;
- versioned model-based checks where deterministic checks cannot express the
  quality judgment.

For outcomes and counts, report the individual values, mean, standard deviation,
median, minimum, and maximum. For latency and cost, also report p50, p95, and p99
only when the sample size supports them. Make model-evaluator variability and
version visible.

For every configured limit, show:

- measured value;
- configured limit;
- met or exceeded;
- direction and size of the difference.

Do not convert these measurements into a deployment recommendation.

## Phase 8.7 — Result contract and evidence package

Produce an immutable JSON result with:

- whole-experiment summary;
- workflow and scenario-group summaries;
- per-scenario results;
- every iteration and trace;
- outcome and state changes;
- tool paths and counts;
- retries and errors;
- latency, token, and cost measurements;
- configured limits and observed differences;
- averages, spread, and individual observations;
- all scenario, code, configuration, fixture, evaluator, and evidence versions;
- operational failures separated from agent behavior.

The result reports the experiment. It does not recommend what to do.
Textual and immutable JSON are the required result surfaces. PR comments and CI
summaries are optional consumers, not separate result contracts.

## Phase 8.8 — Textual experiment workspace

Extend the existing full-screen Textual interface. Do not create a second
execution path.

The workspace must:

- attach through the control-plane API;
- survive local SSH disconnect and reconnect;
- show experiment, scenario, candidate, ablation, and iteration progress;
- show baseline and candidates side by side;
- let the user drill from summary to scenario to iteration to trace;
- show limits, variability, state changes, tool paths, errors, cost, and latency;
- make operational failure distinct from evaluated behavior;
- export or locate the immutable JSON result;
- support keyboard-only operation, narrow terminals, loading, empty, partial,
  error, cancelled, and complete states.

Rich remains the compatible streaming view. Plain and JSON output remain stable
for automation.

## Phase 8 acceptance

Phase 8 is complete only when:

1. one baseline and at least two candidate or ablation configurations run in
   clean ephemeral VMs;
2. one experiment uses one scenario and another uses a saved suite;
3. repeated iterations are interleaved and variability is visible;
4. Lab-managed and BYOVM runners pass the same contract tests;
5. disconnect and reconnect preserve one ordered event stream;
6. lease expiry produces cleanup and no partial result;
7. deterministic and model-based evaluators retain their versions and evidence;
8. Textual can reconnect and inspect the complete experiment;
9. immutable JSON contains all required provenance and no recommendation field;
10. Ruff, mypy, unit tests, integration tests, and an end-to-end cloud smoke test
    pass.

# Phase 9 — Behavior discovery and Prime Agent workflow

## Outcome

Turn opt-in production traces into a dated behavior report, several reviewable
scenario drafts, and an explicit path to a Phase 8 experiment.

## Trace intake

- Support LangSmith and OpenTelemetry as the first trace sources.
- Let a project opt in by source and workflow.
- Apply the configured raw-trace policy at intake.
- Run discovery in batches, not continuously.
- Let projects trigger a batch by schedule, minimum new trace count, or release.
- Compare the current window with the previous window and, when configured, the
  last approved release.

## Behavior discovery

- Group within the declared workflow or task.
- Detect unsafe or poor behavior and efficient successful behavior worth
  preserving.
- Include successful and failed counts.
- Apply configured minimum evidence thresholds.
- Update an existing insight with new evidence and trend instead of duplicating
  it.
- Create a dated discovery report. Put important insights in the inbox.

Each insight includes:

- detected behavior and workflow;
- successful and failed trace counts;
- violated workflow limit when applicable;
- outcome, state, cost, latency, tool, and retry differences;
- representative traces;
- estimated impact;
- grouping confidence, clearly not causal certainty;
- several proposed YAML scenarios.

Configured limit violations appear in the report. Notification behavior remains
configurable. Do not add an opaque ranking model for the MVP.

## Prime Agent handoff

```text
batch discovery
  -> Prime Agent reviews sanitized evidence
  -> explains why it matters
  -> drafts several YAML scenarios
  -> drafts or sends a developer notification
  -> human reviews and approves
  -> approved scenario is published
  -> approved experiment starts
```

The discovery threshold and Prime Agent system prompt decide whether an insight
is worth a developer ping. Destinations are configurable per workflow: Slack,
Linear, email, or webhook.

Before approval, Prime Agent can:

- inspect sanitized evidence;
- compare discovery windows;
- draft an explanation and YAML;
- prepare and send the configured notification.

Before approval, Prime Agent cannot publish a scenario or run an experiment.
After explicit approval, it can publish through the configured Git or managed
storage path and start the requested cloud experiment.

The audit record includes source insight and trace references, Prime Agent model
and prompt version, approved YAML, approving administrator, final stored version,
and experiment identity. If Prime Agent fails, the original insight remains
available for manual review.

# Phase 10 — Hosted operations and MVP hardening

## Outcome

Operate the complete loop for real projects without broadening the product.

- Make all workflow, discovery, data, runner, budget, retention, and notification
  settings configurable through Admin and API.
- Harden Lab-managed VM provisioning and customer BYOVM enrollment.
- Add audit views for approvals, published contracts, runner leases, credentials,
  evidence uploads, and cleanup.
- Add operational alerts for stuck discovery, missing runner capacity, expired
  leases, cleanup failures, and result upload failures.
- Prove tenant isolation and project-scoped access.
- Add backup, restore, retention, and deletion procedures for control-plane data.
- Run end-to-end acceptance with LangSmith and OpenTelemetry sources.
- Run one end-to-end flow through Slack or Linear approval notification.

## MVP completion definition

The MVP is complete after Phase 10 when a company can:

1. register a workflow and opt in a trace source;
2. receive a useful batch behavior report;
3. inspect evidence for successful or failed abnormal behavior;
4. approve a human-edited YAML scenario drafted by Prime Agent;
5. run a repeated, isolated baseline-versus-candidate experiment in Lab or
   BYOVM compute;
6. reconnect to the live Textual workspace;
7. inspect immutable, neutral results at every level;
8. make its own release decision from the evidence.

# Interface direction after the terminal MVP

This section preserves the approved UI reference. It does not authorize a new
web interface during Phases 8–10.

## Product interface concept

Build a **simulation workbench**, not a generic observability dashboard. The
four primary areas remain Insights, Scenarios, Experiments, and Admin. Use
compact tables and evidence panels. Use progressive disclosure for raw traces.
Keep provenance visible:

```text
source evidence -> behavior insight -> scenario -> experiment -> iteration -> result
```

Each step shows its status, version, stable identifier, and backward links.

## UI reference and implementation system

- Use [Kumo](https://kumo-ui.com/) as the first React component and visual
  system when a web interface is approved.
- Verify the current Kumo version, accessibility, and React/Tailwind
  compatibility at implementation time.
- Use Kumo components where they meet the behavior. Build project-owned
  components from accessible primitives where needed.
- Use [TanStack Table](https://tanstack.com/table/latest) behavior with Kumo
  styling for advanced data grids.
- If Kumo blocks two or more core requirements, evaluate
  [shadcn/ui](https://ui.shadcn.com/) with accessible primitives and TanStack
  Table.
- Use [Paper](https://paper.design/) as the shared visual workbench, not as the
  production component library or behavior source of truth.
- Use the [Paper MCP workflow](https://paper.design/docs/mcp) to inspect an
  accepted frame before implementation.
- Keep Simulate's own identity. Do not copy Cloudflare or an observability
  vendor's brand.

For each future web slice:

1. define the user decision, data, actions, states, and evidence;
2. explore two or three layouts with realistic synthetic content;
3. accept desktop and narrow layouts plus loading, empty, error, partial, and
   permission states;
4. inspect the selected Paper frame;
5. translate it into Kumo and project-owned components;
6. verify keyboard behavior, focus, overflow, responsiveness, and visual match;
7. record lasting token and interaction decisions here or in code.

## Interface rules

- Optimize for evidence density and calm hierarchy, not decorative cards.
- Use restrained typography and semantic status colors.
- Never use color as the only status signal.
- Keep important evidence out of tooltips.
- Use banners for states that need attention and toasts for completed background
  work.
- Require confirmation for production-facing decisions.
- Show loading, empty, partial, error, cancelled, and complete states.
- Keep all actions reachable by keyboard.
- Do not expose raw secrets or unrestricted trace payloads.

## Learned interface language

The accepted Textual workbench establishes Simulate's interface character. Use
these principles for later terminal work and translate them to a future web
interface instead of replacing them with a generic software dashboard.

### Visual character

- Treat the interface as a focused work tool: quiet, precise, and centered on
  evidence. The event timeline and visible provenance are its signature.
- Use true black as the main working surface, charcoal for focus and selection,
  soft white for primary text, and gray for secondary information.
- Reserve muted yellow for warnings and approvals, and red for failures. Do not
  introduce a general-purpose bright accent color.
- Build hierarchy with spacing, alignment, text weight, and thin rules. Prefer
  open rows and continuous work surfaces over nested panels and card grids.
- Do not add gradients, ornamental shadows, decorative charts, or rounded
  containers without a specific information or interaction need.
- Keep typography compact and editorial. A future web interface can use a
  deliberate type pairing, but it must preserve the terminal's direct,
  focused tone rather than adopt a generic software-service style.

The current terminal palette is a reference, not a requirement for identical
web color values: black `#000000`, focus charcoal `#202020`, primary white
`#f2f2f2`, secondary gray `#a0a0a0`, warning yellow `#e5c558`, and failure red
`#ef5b5b`.

### Interaction character

- Ask for one decision at a time during setup, then show one compact review
  before execution. Do not display a wall of fields when the choices have a
  useful order.
- Keep the main evidence stream visually dominant. Context and details may move
  to secondary rails, but the primary row must retain identity, source, status,
  and meaning when those rails are hidden.
- Make keyboard focus unmistakable. While a text field has focus, printable
  keys belong to that field and must not activate global shortcuts.
- Keep shortcuts visible in a quiet footer. Use the same action name in the
  shortcut, control, status message, and documentation.
- Prefer immediate, stable state changes. Add motion only when it explains
  progress, continuity, or a change of location.
- Design narrow layouts as complete interfaces, not clipped desktop views.
  Remove secondary controls and decoration before removing evidence.

### Interface copy

- Use short lowercase labels for events, statuses, commands, and compact
  controls. Use sentence case for instructions, explanations, and errors.
- Write plain operational copy. Name what happened, what is running, or what the
  person can do next. Do not use slogans or conversational filler.
- Make an error state identify the failed check and give one direct next step.
- Let each label do one job. Do not repeat the same metadata in several nearby
  panels only to fill space.

# Future improvements — not approved for implementation

These items are concrete but outside the core MVP or need a larger decision.

## OpenTelemetry GenAI semantic interoperability — High

**Problem:** The current telemetry allowlist does not map every model, agent,
tool, and MCP field to the shared OpenTelemetry semantic conventions.

**Evidence:** OpenTelemetry now defines GenAI, agent, and MCP conventions.
Phoenix and other tools accept OTLP and OpenInference data.

**Direction:** After Phase 9 proves direct OpenTelemetry intake, version a
privacy-reviewed mapping and migration. Dual-write during the transition.

**Why later:** A field migration affects stored evidence, privacy review, and
external consumers. Direct OTLP intake is core; full semantic convergence is
not.

## Durable multi-worker orchestration — Medium

**Problem:** Runner leases and reconnect support durable remote experiments, but
they do not provide general multi-worker workflow recovery and orchestration.

**Evidence:** Temporal and Hatchet provide persisted histories, retries, leases,
and worker coordination.

**Direction:** Measure Phase 8 failure and throughput behavior. Define the
persisted state machine, retry, cancellation, and idempotency contracts before
choosing an orchestrator.

**Why later:** This is an operations architecture change. It is not required to
prove the single-experiment product loop.

## Domain-neutral workflow contracts — Medium

**Problem:** Reference domains still have parallel state, authorization, and
fixture adapters.

**Evidence:** The repository has several executable reference workflows and a
generic simulator event/plugin seam. Inspect and SWE-bench also separate task
data, execution, and scoring.

**Direction:** Measure the stable overlap, then converge scenario, dependency,
state-transition, and evaluator interfaces without erasing domain policy.

**Why later:** A premature common model can weaken safety boundaries and make
the code less readable.

## Automatic Prime Agent remediation — Low

**Problem:** A mature system could investigate, simulate, patch, and validate a
workflow with little operator work.

**Evidence:** Current coding agents can inspect repositories and use disposable
cloud workspaces.

**Direction:** Let Prime Agent propose a patch and experiments inside a sandbox,
then require human review for code, scenario, execution, and release.

**Why later:** Automatic remediation materially expands autonomy and product
scope. The MVP must first prove insight quality and experiment trust.

## Automatic deployment — Low

**Problem:** Teams can act faster if accepted evidence connects to release
systems.

**Direction:** Export stable result status and evidence to customer CI or
deployment policy. Keep the decision customer-owned.

**Why later:** Simulate is an evidence system. Deployment control is a separate
high-risk capability.

## Partial experiment recovery — Low

**Problem:** Large experiments can waste completed work after a lease or runner
failure.

**Direction:** Add immutable per-iteration commits and resumable experiment
aggregation only after the result semantics are proven.

**Why later:** The MVP intentionally discards incomplete results. Recovery adds
complex state, cancellation, and statistical rules.

## Learned feedback from review actions — Low

**Problem:** Dismissals and edits could improve insight selection over time.

**Direction:** Study explicit, consented feedback with a transparent evaluation
set before any training or ranking use.

**Why later:** The MVP stores dismissal reasons for audit, not model training.

## Organization roles — Low

**Problem:** Larger customers may need separate viewer, editor, approver, and
infrastructure roles.

**Direction:** Add the smallest roles shown necessary by real access patterns.

**Why later:** All members are administrators for the MVP. Speculative RBAC
would slow the core workflow.

## Web workbench — Medium

**Problem:** Some teams will prefer a shared browser interface to SSH and a
terminal workspace.

**Direction:** Apply the Kumo and Paper design system above to the same
control-plane API after the terminal MVP is validated.

**Why later:** A new web application would duplicate product-surface work before
the experiment and discovery contracts stabilize.

# Upstream patterns and product decisions

No upstream implementation has been copied. These projects inform specific
local patterns:

| Source | Pattern used or reserved |
| --- | --- |
| [Inspect](https://inspect.aisi.org.uk/) and [SWE-bench](https://www.swebench.com/) | Keep scenario data, execution, and evaluation separate. |
| [OpenHands SDK](https://docs.openhands.dev/sdk/) | Separate the agent, workspace, event stream, and client UI. Rich and Textual consume the same events. |
| [Playwright traces](https://playwright.dev/docs/trace-viewer) | Package inspectable evidence with a result instead of reporting an unsupported claim. |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Use persisted checkpoints and explicit human interrupts for controlled workflows. |
| [LangSmith Insights](https://docs.langchain.com/langsmith/insights) | Discover usage patterns and agent behaviors, then inspect supporting traces and measurements. |
| [LangSmith experiments](https://docs.langchain.com/langsmith/evaluation) and [comparison](https://docs.langchain.com/langsmith/compare-experiment-results) | Move traces into datasets and experiments; compare scenario results, traces, cost, and latency. |
| [LangSmith repetitions](https://docs.langchain.com/langsmith/repetition) | Repeat stochastic evaluations and show mean and standard deviation. |
| [Braintrust Topics](https://www.braintrust.dev/foundations/analyzing-production-logs) | Cluster production logs into named, reviewable behavior categories. |
| [Braintrust experiments](https://www.braintrust.dev/docs/evaluate/run-evaluations) | Preserve immutable experiment trials and compare them without hiding examples. |
| [Phoenix experiments](https://arize.com/docs/phoenix/get-started/ts-get-started-datasets-and-experiments) | Inspect experiments and examples side by side. |
| [Langfuse annotation queues](https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues) | Preserve a human review step for selected production evidence. |
| [OCI image specification](https://oci-playground.github.io/specs-latest/specs/image/v1.1.0-rc2/oci-image-spec.pdf) | Use content digests as immutable executed image identity. |
| [GitHub self-hosted runners](https://docs.github.com/en/actions/reference/runners/self-hosted-runners) | Prefer ephemeral runners for untrusted or isolated work. |
| [E2B networking](https://e2b.dev/docs/api-reference/sandboxes/create-sandbox) | Make sandbox network access explicit and allowlisted. |
| [Temporal](https://docs.temporal.io/workflows) and [Hatchet](https://docs.hatchet.run/) | Reserve general durable orchestration until the local state machine is proven. |

## Explicit implementation choices

- Keep Textual. Do not add OpenTUI and a second TypeScript or Bun runtime only
  for terminal presentation.
- Keep one simulator event stream and plugin seam. Do not fork the execution
  engine for Rich, Textual, API, or future web clients.
- Do not fork a full external agent runtime. Borrow stable boundaries and
  protocols.
- Do not add Temporal or Hatchet before Phase 8 defines experiment states,
  leases, retry, cancellation, event offsets, and cleanup.
- Do not turn results into recommendations. Product value comes from realistic
  scenarios, controlled runs, inspectable evidence, and a good workflow.
