# Upstream patterns and decisions

This note records which 2026 ecosystem patterns fit the current product. No
upstream source code was copied in this work.

## Applied now

| Source | Pattern used | Local decision |
| --- | --- | --- |
| [Inspect](https://inspect.aisi.org.uk/) and [SWE-bench](https://www.swebench.com/) | Separate a task dataset, execution logic, and acceptance scoring. | Keep scenario data in YAML, run it through one plugin engine, and judge it with explicit evidence and verdict contracts. |
| [OpenHands SDK](https://docs.openhands.dev/sdk/) | Keep the agent, workspace, event stream, and client UI separate. | Rich and Textual consume the same simulator events. The renderer does not own execution or persistence. |
| [Playwright traces](https://playwright.dev/docs/trace-viewer) | Package observed evidence with a result instead of reporting a claim alone. | Simulation, proof, reference, and audit reports retain stable evidence identifiers and machine-readable verdicts. |
| [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | Use durable checkpoints and explicit interrupts for human approval. | Controlled workflows use the official PostgreSQL saver and bind resume actions to the original actor and request. |

## Keep as a future phase

| Source | Useful pattern | Why it stays future work |
| --- | --- | --- |
| [OpenTelemetry GenAI conventions](https://opentelemetry.io/docs/specs/semconv/) | Shared agent, model, token, and tool telemetry names. | The conventions are still changing. A migration affects stored evidence and privacy review. |
| [Temporal](https://docs.temporal.io/workflows) and [Hatchet](https://docs.hatchet.run/) | Durable execution, retries, leases, and multi-worker recovery. | This needs a persisted run-state contract before an orchestrator choice. |
| [E2B](https://github.com/e2b-dev/E2B), [Cua](https://github.com/trycua/cua), and [OneCLI](https://github.com/onecli/onecli) | Disposable remote sandboxes and brokered credentials. | These add cloud lifecycle, cost, and secret-policy scope. |
| [Langfuse](https://langfuse.com/docs) and [Traceloop](https://www.traceloop.com/docs) | OTLP-based trace interoperability and replay views. | The product must first define its stable OpenTelemetry mapping. |

## Rejected for this phase

- Do not fork a full agent runtime. The current agent and simulator contracts
  already cover the product's existing execution flow.
- Do not add a second TypeScript or Bun runtime only for OpenTUI. Textual gives
  the Python CLI a full-screen interface while preserving one execution path.
- Do not add a durable workflow engine before run cancellation, retries,
  retention, and event-offset semantics are explicit.
