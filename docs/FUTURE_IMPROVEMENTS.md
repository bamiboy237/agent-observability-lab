# Future improvements

These ideas are evidence-based, but they expand the current product or need a
larger design decision. They were not implemented during the codebase
simplification pass.

## Idea

Standard OpenTelemetry GenAI interoperability.

## Problem

The product uses a private telemetry allowlist. External OpenTelemetry tools
cannot interpret all model and agent fields without a custom mapping.

## Evidence

The [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/)
now include shared GenAI, agent, and Model Context Protocol conventions.
[Phoenix](https://arize.com/docs/phoenix/) accepts OTLP traces and uses
OpenInference instrumentation across common agent frameworks.

## Proposed direction

Version a small dual-write mapping from the current privacy-reviewed fields to
stable OpenTelemetry GenAI fields. Preserve the private fields until consumers
and historical comparisons migrate.

## Why not implemented now

Telemetry field changes affect stored evidence, privacy review, dashboards,
and external consumers. The stable subset and migration policy need a separate
contract decision.

## Priority

High.

## Idea

Stochastic comparison controls.

## Problem

One hosted-model run per case can make a comparison look decisive when the
observed result is normal model variance.

## Evidence

[LangSmith evaluation guidance](https://docs.langchain.com/langsmith/evaluation-types)
separates deterministic code checks from model-based evaluation and supports
benchmarking, regression testing, backtesting, and pairwise comparison over
curated datasets.

## Proposed direction

Add an explicit experiment policy for repetitions, concurrency, cache use,
variance summaries, and minimum comparable runs. Keep deterministic safety
checks as hard gates.

## Why not implemented now

This changes execution cost, report schemas, recommendation thresholds, and
the meaning of a passing comparison.

## Priority

High.

## Idea

Durable multi-worker run execution.

## Problem

In-process run tasks and live subscriber queues do not survive a process
restart and are not a safe coordination mechanism across several API workers.

## Evidence

[Temporal](https://docs.temporal.io/workflows) keeps ordered workflow history
as the source of truth and replays deterministic workflow code after worker
failure. [Hatchet](https://docs.hatchet.run/) provides PostgreSQL-backed task
persistence, retries, replay, and worker monitoring. The current repository
already persists final reports and evidence, but not the execution coordinator.

## Proposed direction

Define a persisted run state machine and lease protocol before selecting a
queue or workflow engine. Reconnect live views to durable event offsets.

## Why not implemented now

This is a deployment architecture change, not a local reliability fix. It
requires failure, retry, cancellation, and retention contracts.

## Priority

Medium.

## Idea

Remote attachment for live simulator runs.

## Problem

The Textual workspace works over SSH while its process remains attached, but a
user cannot start a run through the API and later attach the same interface from
another terminal. A dropped SSH connection can also end a foreground CLI run.

## Evidence

The [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk/)
separates conversations, workspaces, events, and clients. Its remote agent
server exposes the same conversation through HTTP and WebSocket clients. This
repository already exposes run status and Server-Sent Events, so the missing
piece is transport separation rather than another renderer.

## Proposed direction

Define one event-source interface for the Textual renderer. Keep the current
in-process source and add an HTTP status plus SSE source for existing `/runs`
endpoints. Resume from a durable event offset only after the execution service
itself becomes durable.

## Why not implemented now

The current API run service stores execution handles in process memory. A
remote viewer without durable run identity and event offsets would imply
reconnect guarantees that the server cannot yet provide.

## Priority

High.

## Idea

Provider-neutral remote sandboxes and credential placeholders.

## Problem

Remote agent execution eventually needs stronger isolation than a local test
database and should not expose provider credentials inside the agent process.

## Evidence

[E2B](https://github.com/e2b-dev/e2b) and
[Cua](https://github.com/trycua/cua) expose disposable remote sandbox APIs.
[OneCLI](https://github.com/onecli/onecli) uses placeholder credentials and a
gateway that injects scoped real credentials outside the agent process.

## Proposed direction

Keep the existing environment profile and provisioner contracts
provider-neutral. Evaluate one sandbox adapter and one credential-broker
boundary only after remote execution is an accepted product requirement.

## Why not implemented now

This adds cloud resource lifecycle, cost limits, secret policy, and audit
semantics. Those are new deployment capabilities, not improvements to the
current local simulator.

## Priority

Medium.

## Idea

Domain-neutral reference workflow contracts.

## Problem

Reference workflows and support simulations use parallel adapters and fixture
shapes. Adding more reference domains will increase mapping code and make
comparison behavior harder to keep consistent.

## Evidence

The repository already contains seven executable reference workflows and a
generic simulator plugin contract. The overlap is real, but the state,
authorization, and tool contracts still differ by domain.

## Proposed direction

Measure the common contract from the current seven workflows, then converge on
one scenario, dependency, state-transition, and verdict interface. Preserve
domain-specific state and policy models behind adapters.

## Why not implemented now

This is a broad architecture decision. A forced merge now could weaken the
safety boundaries and create a less readable abstraction.

## Priority

Medium.
