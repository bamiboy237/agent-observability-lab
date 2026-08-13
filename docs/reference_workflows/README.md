# Reference Workflows

Design documents and offline fixture data for realistic 2026 agentic
workflows that the simulation lab can adopt as reference workflows. Each
workflow is distinct from the existing customer-support workflow and from
one another:

| Workflow | Domain | Design document | Fixture module | Comparison variable |
|---|---|---|---|---|
| Returns Resolution Agent | E-commerce returns and refunds | `returns-resolution-agent.md` | `src/app/domain/reference_workflows/returns_resolution.py` | refund confirmation gate |
| Onboarding Coordinator Agent | HR onboarding | `onboarding-coordinator-agent.md` | `src/app/domain/reference_workflows/onboarding.py` | checklist selection source |
| Dispute Resolution Agent | Banking disputes | `dispute-resolution-agent.md` | `src/app/domain/reference_workflows/disputes.py` | evidence source minimum |

All fixture modules are self-contained (stdlib only), deterministic, and
offline-runnable. No existing lab code was modified; the design documents
describe how each workflow maps to the lab's evidence, scenario, and bundle
contracts and which generalization points a future phase needs.
