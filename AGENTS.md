# Repository agent instructions

## Purpose

Build **Simulate**: a system that continuously evaluates and improves agentic
workflows.

The core loop is:

```text
production traces
  -> behavior insights
  -> human-approved YAML scenarios
  -> isolated repeated experiments
  -> neutral evidence
```

Simulate reports experiment results. It does not recommend a deployment.

## Authority

- Read `BUILD_ROADMAP.md` before product, architecture, phase, or interface work.
- Treat `BUILD_ROADMAP.md` as the source of truth for product language, approved
  scope, phase order, contracts, UI references, and future work.
- Read `docs/user-simulator.md` before changing simulator CLI or terminal
  behavior.
- Treat tests and code as the source of truth for current implemented behavior.
- If roadmap and code differ, state the difference. Do not present planned work
  as implemented work.

Do not create another strategy, architecture, upstream-pattern, or future-work
Markdown file. Add durable product decisions to `BUILD_ROADMAP.md`. Add a small
operational document only when a user must follow a separate procedure.

## Current boundary

- Phases 0–7 are complete on `main` through `f31c438`.
- Phase 8 is next and is not implemented.
- Do not implement Phase 8 or a later phase without explicit user approval.
- Do not expand the MVP with automatic deployment, automatic remediation,
  speculative roles, a new web application, or partial experiment recovery.

## Product language

- Product name: **Simulate**.
- Tagline: **Continuously evaluate and improve agentic workflows.**
- Say **behavior insight**, not **failure cluster**, in new product surfaces.
- Say **simulate**, not **replay**, as the primary verb.
- A **scenario** is a human-approved YAML contract.
- An **experiment** compares a baseline with one or more candidates through
  repeated, controlled iterations.
- A **result** contains evidence and measurements. It does not contain a release
  recommendation.

Do not mechanically rename stable older modules. Migrate public contracts in a
reviewable checkpoint and keep compatibility where required.

## Engineering rules

1. Prefer one execution path. Put workflow differences in versioned data or
   contracts.
2. Use the standard library, the framework, or an existing dependency before a
   new abstraction or dependency.
3. Keep domain rules in services and contracts. Keep API, CLI, Rich, Textual,
   and future web code as clients of the same behavior.
4. Keep trace ingestion, scenario construction, execution, evaluation, and
   presentation separate.
5. Treat a trace as evidence, not as approved state or expected behavior.
6. Require explicit human approval before publishing generated YAML or starting
   a Prime Agent experiment.
7. Preserve exact scenario, code, image, model, prompt, tool, policy, fixture,
   evaluator, and evidence versions.
8. Use repeated and interleaved runs for stochastic comparisons.
9. Report averages, spread, limits, and individual iterations. Do not hide them
   behind one score.
10. Keep cloud execution provider-neutral. Lab-managed and BYOVM runners must
    implement the same contract.
11. Use ephemeral compute, expiring leases, short-lived credentials, outbound
    allowlists, and explicit cleanup.
12. Keep Textual attached to the control-plane API, not directly to a runner VM.
13. Plain JSON is the stable automation output.
14. Do not claim deterministic, isolated, private, durable, remote, or safe
    behavior without a focused test of that boundary.

## Delivery workflow

For each meaningful change:

1. identify the current behavior and its consumers;
2. separate observed facts, likely causes, proposals, and unknowns;
3. choose the smallest complete change;
4. update code, callers, contracts, tests, and documentation together;
5. run focused validation;
6. run the broad practical quality gate before completion;
7. record completed roadmap evidence without deleting known limitations.

Preserve user changes in a dirty worktree. Do not perform a speculative rewrite.
Do not add an abstraction only to remove repeated lines. Optimize for fewer
concepts, fewer files, and one obvious path.

## Quality gate

Use the repository environment and run, at minimum:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

Database integration tests require PostgreSQL. The complete sandbox check is:

```bash
docker compose --profile test run --rm test
```

State exactly which checks ran and which checks could not run.

## Communication

Use short, concrete sentences. Define a project-specific term before using it.
For a defect, state:

1. what the object is and who uses it;
2. what should happen;
3. what happens instead and under which conditions;
4. one concrete example;
5. what the user can observe;
6. whether the cause is observed, likely, proposed, or unknown;
7. the smallest permanent fix;
8. one focused verification check.

For progress, state the goal, completed work, why it matters, next step, and any
blocker or risk. Follow ASD-STE100 Simplified Technical English where practical.
