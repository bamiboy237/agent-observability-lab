# Reference Workflow: CI Failure Triage Agent

- Workflow id: `ci_triage_agent`
- Workflow version: `1.1.0`
- Fixture module: `fixtures.py` in this directory
- Status: reference design, offline-runnable, not wired into lab phases

## 1. Domain

The **CI failure triage agent** is a 2026 developer-tooling workflow. When a
pull request check run fails, the agent reads the failing checks and their
logs, classifies the failure (flaky test vs deterministic regression vs
infrastructure failure), checks the commit history and known issues, and then
either posts a grounded triage comment, files a triage report issue, or
proposes a fix branch. The agent never changes code without a confirmed,
evidence-backed classification.

Real-world grounding (2026):

- **CodeRabbit's "Fix CI" flow**: "it reads the failing checks and their
  output, works through the fix in a sandbox, and opens a stacked pull request
  with the changes so you can review them before they land" (CodeRabbit docs,
  https://docs.coderabbit.ai/finishing-touches/fix-ci). The agent gathers the
  failure output and the CI configuration "rather than guessing from the check
  name alone."
- **Elastic's Flaky Test Investigator** is a GitHub Actions agent that
  "discovers flakiness labels, searches open issues for flaky-test reports,
  and inspects recent failed CI runs. Builds a frequency map of failing tests
  across runs and issues, then files a single triage report with
  root-cause-first recommendations when there is concrete evidence of
  flakiness" (https://elastic.github.io/ai-github-actions/workflows/gh-agent-workflows/flaky-test-investigator/).
  Note the permission split in its workflow file: `actions: read`,
  `contents: read`, `issues: write`, `pull-requests: read` — reads are broad,
  writes are narrow.
- **Flaky vs regression classification** is the core correctness question: a
  flaky test must not trigger a code change, and a regression must not be
  dismissed as flaky.

This workflow differs from customer support: the "customer" is a failed check
run, the answer is a classification plus (optionally) a code mutation, and the
most sensitive action (creating a fix branch) changes real source code.

## 2. Turn flow

1. A failed `workflow_run` on a pull request triggers the agent.
2. Agent reads the failing check runs for the pull request head commit.
3. Agent reads test results and log snippets for the failing checks.
4. Agent reads the branch commit history.
5. Agent searches known issues for the same failure signature (retrieval).
6. Agent classifies: flaky / regression / infrastructure.
7. Grounded actions only: comment on the PR, file a triage report, or (with
   confirmation) create a fix branch.

## 3. Stateful system

Owned system (an ephemeral copy in the lab; records in `fixtures.py`):

| Entity | Key fields | Statuses |
| --- | --- | --- |
| `Repository` | id, name, default_branch | - |
| `PullRequest` | id, repo_id, number, title, branch, status, author | open, merged, closed |
| `CheckRun` | id, pull_request_id, name, status, conclusion, failure_summary | queued, in_progress, completed; success / failure / cancelled |
| `TestResult` | id, check_run_id, test_name, outcome, duration_ms, log_snippet | passed, failed, flaky |
| `Commit` | id, repo_id, sha, message, author | - |
| `Issue` | id, repo_id, title, labels | open (labels include `flaky-test`) |

State machine (check run): `queued -> in_progress -> completed`. The agent's
writes are: a comment on a pull request, a new triage issue, and a new fix
branch.

Local-only fields (never traced, never bundled): test log snippets, commit
messages, issue titles, PR titles.

External dependencies needing recorded fixtures or simulators: the git host
(GitHub-style API) and the issue/retrieval index.

## 4. Tools: safe vs sensitive

| Tool | Sensitivity | Confirmation | Why |
| --- | --- | --- | --- |
| `read_failing_checks` | safe | no | read-only |
| `read_test_logs` | safe | no | read-only |
| `get_commit_history` | safe | no | read-only |
| `search_known_issues` | safe | no | retrieval; classification must cite the returned evidence |
| `comment_on_pr` | sensitive | no | writes to a shared PR thread; must be grounded |
| `open_triage_issue` | sensitive | yes | creates a tracked artifact; one per evidence-backed finding |
| `create_fix_branch` | sensitive | yes | mutates source code; only for confirmed regressions, never for flaky tests |

The split follows the 2026 least-privilege pattern: read tools are free, write
tools are gated in code, and the agent's token never has broader permissions
than the workflow needs.

## 5. Baseline/candidate comparison variable

**Failure classifier model** (`failure_classifier_model`):

- Baseline: `gpt-4.1-mini` — cheap classifier.
- Candidate: `gpt-5.2` — stronger classifier.
- Unit: classification accuracy on flaky vs regression; secondary measures are
  unexpected state changes (e.g. fix branches created for flaky tests),
  latency, and cost.
- Scenario `ref-ci-01-flaky-misclassified`: `test_checkout_retry_on_network_error`
  failed 2 of the last 40 runs and passes on rerun, and a known flaky-test
  issue exists. The baseline labels it a regression and creates a fix branch
  (wrong state change). The candidate labels it flaky and files a triage
  report (correct). This maps directly to the lab's Model Lab: same scenario,
  tools, state, prompt, and evaluators; only the model changes.

## 6. Mapping to the lab contracts

### Evidence contract (`TraceEvidence`)

| Lab field | Mapping for this workflow |
| --- | --- |
| `workflow`, `workflow_version` | `ci_triage_agent`, `1.1.0` |
| `outcome` | completed / blocked / escalated / failed |
| `reason_code` | `flaky_identified`, `regression_identified`, `infra_failure_identified`, `triage_report_filed`, `ungrounded_classification`, `ok_with_retry`, ... |
| `events` | turn, model, tool, retrieval (`search_known_issues`), retry, step |
| `dependency_calls` | one per tool call; `error_code` values `timeout`, `confirmation_required` |
| `policy_decisions` | one per classification decision (version, decision, reason_code) |
| `confirmation` | required=true for `open_triage_issue` and `create_fix_branch` |
| `task_input` / `task_output` | needs a per-workflow allowlist extension (e.g. `ci.check.name`, `ci.classification`, `ci.flaky.frequency`) |
| `trace attributes` | needs per-workflow keys in `TRACE_ATTRIBUTE_ALLOWLIST` (e.g. `ci.check.conclusion`, `ci.classification.grounded`) |

The fixture `TraceFacts` projection carries the decision facts (classification
decisions, confirmation, retry, timing, tokens, cost) offline.

### Scenario contract (`SimulationScenario`)

| Lab field | Mapping for this workflow |
| --- | --- |
| `scenario_id` | `ref-ci-01-flaky-misclassified` |
| `category` | reuse `SimulationCategory` (`answer_failure`, `infrastructure_failure`, `policy_failure`, ...) |
| `request` | `TriageRequest` (pull_request_id, check_run_id, trigger) — `SupportRequest` is support-fixed; needs parameterization |
| `workflow_context` | reuse `WorkflowContext` unchanged |
| `initial_state` | `CiState` (repositories, pull_requests, check_runs, test_results, commits, issues) |
| `eligible_actions` | the 7 tools above |
| `expected_behavior` | reuse `ExpectedBehavior`; `ExpectedStateTransition.resource` pattern must extend to `pull_request`, `issue`, `branch`, `check_run` |
| `original_production_behavior` | reuse unchanged |
| `required_dependency_coverage` | reuse; `github` (stateful), `issue.retrieval` (recorded) |
| `evidence_ref` | reuse; trace ids like `ref-ci-01-flaky-misclassified-baseline` / `-candidate` |
| `local_only_fields` | reuse; log snippets, commit messages |
| `content_hash` | same canonical-JSON mechanism |

### Bundle contract (`SimulationBundle`)

| Lab field | Mapping for this workflow |
| --- | --- |
| `bundle_id` / `content_hash` | same derive-from-content mechanism |
| `BundleRequest` | needs parameterization (`TriageRequest` projection) |
| `resource_seeds` | one `EnvironmentResourceSeed` per resource (`repository`, `pull_request`, `check_run`, `test_result`, `commit`, `issue`) |
| `dependency_fixtures` | reuse; recorded payloads for `issue.retrieval` |
| `fault_script` | reuse; inject `timeout` at the `github` log-read boundary |
| `review`, `redaction_decisions`, `coverage` | reuse unchanged |

## 7. Scenarios in the fixture module

| Scenario | Category | Behavior the lab must reproduce |
| --- | --- | --- |
| `ref-ci-01-flaky-misclassified` | answer_failure | flaky failure must not produce a fix branch; baseline/candidate model comparison |
| `ref-ci-02-log-timeout` | infrastructure_failure | one timeout, retry succeeds, regression classified with evidence |
| `ref-ci-03-fix-without-evidence` | policy_failure | fix branch without a confirmed classification is blocked; no state changes |

## 8. Boundaries

- The agent may classify only from retrieved evidence (logs, run history,
  known issues); an ungrounded classification cannot produce a comment,
  issue, or branch.
- Fix branches are simulated writes in the lab; the git host is a stateful
  adapter or recorded fixture, never a real repository.
- One agent per failed check run; no multi-agent graph.
- Fully offline-runnable: `uv run python -c "import app.domain.reference_workflows.ci_triage.fixtures"`.
