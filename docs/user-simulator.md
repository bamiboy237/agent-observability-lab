# User simulator: live runs and timelines

The user simulator runs a persona against a real product agent (the support
sandbox or a reference workflow) behind a guided setup wizard, then streams
one append-only operational timeline to the terminal.

The only launch path is the generic CLI: scenarios are configured as grouped
YAML catalogs (`simulations/*.yaml`) and safe environment profiles
(`config/simulation-environments.yaml`). There are no per-scenario wrapper
scripts.

## The commands

```bash
uv run lab simulate list                 # grouped catalog listing
uv run lab simulate validate             # strict YAML validation
uv run lab simulate run <scenario-id>    # guided setup + preflight + live run
uv run lab simulate run <scenario-id> --yes --max-turns 8
uv run lab simulate run <scenario-id> --view textual
```

- `run` with no id and on a terminal opens the grouped chooser, then lets you
  adjust who is making the request, what they say, the desired outcome, and
  the turn limit before starting.
- `--yes` skips every prompt (non-interactive). Missing required values fail
  instead of prompting. Overrides: `--profile`, `--max-turns`, `--persona`,
  `--script`, `--goal`.
- `--no-live` prints plain one-line events even on a terminal.
- Interactive runs ask whether to use Rich or Textual after setup and preflight.
  Use `--view rich` or `--view textual` to choose without a prompt. `--tui` is
  kept as a compatibility alias for `--view textual`.
- The Textual view is a full-screen command center. Setup is a separate page
  for choosing a scenario, editing the run recipe, and reviewing preflight.
  After launch, `o` opens the run overview, `t` opens the event stream, and `e`
  opens the evidence handoff. The run and persistent log continue while the
  view is paused. The pages support event filtering, safe event details, live
  counts, elapsed time, responsive narrow-terminal layouts, and a verified
  result summary.
- `--json` prints only the stable final report (or the structured
  validation/preflight result).
- `Ctrl-C` after the run has started rolls back the disposable environment,
  writes a partial report (`end_reason: cancelled`), and exits with status
  130.

## Setup review and preflight

After you choose a simulation and profile, the wizard shows a compact review:
scenario, flow, model, database profile (host/port/database label), the `test`
environment, the artifact directory, and the cleanup/isolation mode.

Before any run id or artifact is allocated, a preflight gate validates:

- the plugin is registered;
- `ENVIRONMENT=test`;
- every required environment variable is present (see the profile's
  `required_variables` — these are variable *names*, never secret values);
- the database URL is loopback-only and matches the profile, the database is
  reachable, and migrations are at head;
- the artifact directory is writable.

Each missing item prints one plain fix command/message; nothing is started
until every check passes.

## The timeline

One responsive, append-only timeline, capped at 100 columns for readable SSH
sessions:

- `user` / `agent` lines are the actual in-memory conversation.
- `tool selected` / `tool result` lines are indented under the agent turn
  and show only the safe projected arguments.
- `model`, `state`, `approval`, `retry`, `done`, `error`, and `cleanup`
  lines carry semantic colors plus text labels.
- The display adapts to narrow terminals and identifies each event by marker,
  text label, and source. It does not rely on color alone.
- Values are escaped and capped at 160 characters; chain-of-thought is never
  shown (a fixed `(reasoning unavailable)` note is used instead).

Non-terminal output (pipes, files) prints one plain line per event, still
starting with `run_id=`, `jsonl_path=`, and `report_path=` so existing tail
workflows keep working.

The Textual view is optional. Interactive runs let the operator choose Rich or
Textual; non-interactive live runs keep Rich as the compatibility default, and
plain/JSON output remains the stable automation interface. Textual consumes the
same plugin and event contracts; it does not own execution or persistence. It
stays in the repository's Python runtime and has headless interaction tests.
OpenTUI set a useful 2026 quality reference, but using it here would add a
second TypeScript/Bun/native runtime and duplicate the CLI application boundary.

## What gets persisted

The append-only JSONL log stores only allowlisted persistent fields (turn,
tool, outcome, reason, error, model name/provider, tokens, latency,
attempts, transition, state, verified). Conversation text and tool argument
values are display-only memory and are never written to disk. The final
`SimulatorReport` JSON holds the run summary.

## Scenarios, profiles, and the plugin seam

- `simulations/support.yaml` and `simulations/reference-workflows.yaml` are
  grouped catalogs: each entry references a registered `plugin_id`, carries
  friendly metadata (name, description, persona/script/goal defaults, max
  turns), and names a default environment profile. YAML is metadata only —
  no tool code, commands, or secrets. The strict loader and its schema live
  in `src/app/domain/user_simulator/manifests.py` (see that module's tests
  for the exact validation rules).
- `config/simulation-environments.yaml` holds non-secret environment
  profiles. Secret values are referenced by environment variable name and
  resolved at runtime; nothing secret ever appears in YAML or in output.
- The flow registry is authoritative for executable code. The YAML catalog is
  authoritative for setup defaults. A new registered `FlowPlugin` plus one
  YAML catalog entry appears in `lab simulate list`
  and runs through the same wizard/viewer with zero CLI edits. Duplicate
  scenario ids and unknown plugin/profile ids fail validation with
  `filename: field` messages.

## Local run example

The shipped `lab-test-pg` profile targets the disposable local database on
`127.0.0.1:55433/lab` and requires the following environment variables
(keep their values out of YAML and out of the repo):

```bash
export ENVIRONMENT=test
export LAB_TEST_PG_URL=<local disposable database URL>   # loopback only, no credentials in the command
export MODEL_PROVIDER=openai
export MODEL_NAME=gpt-5.6-luna
export MODEL_API_KEY=<reviewed root model key, local only>
uv run lab simulate run phase2-03-database-timeout --max-turns 8
```

The selected profile's database URL is resolved from `LAB_TEST_PG_URL` at
runtime and injected into the run; a conflicting root `DATABASE_URL` is never
consulted for execution. The setup review edits (caller context, request,
desired outcome) and the `--persona`/`--script`/`--goal` flags are applied to
the run's persona by the adapter.
