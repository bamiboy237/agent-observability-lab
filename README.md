# Simulate

Continuously evaluate and improve agentic workflows.

Simulate turns opt-in production traces into behavior insights, human-approved
YAML scenarios, isolated repeated experiments, and neutral evidence. The current
repository contains the completed Phases 0–7 foundation. Phase 8, the controlled
experiment engine, is planned but not implemented.

See `BUILD_ROADMAP.md` for the product contract, current phase boundary, cloud
and BYOVM direction, Textual workflow, and preserved Kumo/Paper UI reference.

## Local setup

Requirements: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and a PostgreSQL
database. This workspace is linked to Neon, so authenticated contributors can
pull the current development branch configuration:

```bash
neon env pull --file .env
uv sync --frozen
uv run alembic upgrade head
```

### Docker sandbox

Docker Compose starts a local PostgreSQL database and the API. It uses a named
Docker volume for database data and binds both services to loopback only. The
database is available on host port `55433`.

```bash
docker compose up --build
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

Run the test suite in the same sandbox:

```bash
docker compose --profile test run --rm test
```

The test service uses only explicit disposable-database settings. It does not
load `.env` or run credentialed live-model checks.

Stop the services with `docker compose down`. Add `-v` only when you want to
remove the local database volume and all data stored in it.

Start the API:

```bash
uv run uvicorn app.main:create_app --factory
```

Then verify liveness and database readiness:

```bash
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

## Controlled support workflows

The workflow API persists LangGraph checkpoints in PostgreSQL. On the first
workflow request, the API opens the configured direct database connection and
idempotently creates the checkpointer tables with the official saver. A later
API worker can inspect or resume the same workflow by its stable workflow ID.
The normal Alembic migration command still manages application tables; the
checkpointer's explicit setup manages only its own tables.

```bash
curl -X POST http://127.0.0.1:8000/workflows \
  -H 'content-type: application/json' \
  -d '{"actor_id":"<customer-uuid>","request_id":"demo-1","message":"Where is my order <order-uuid>?"}'
```

## User simulator CLI

Run the bare command to open the full-screen Textual workbench. It uses a
restrained black and charcoal interface with open tables, thin rules, plain
copy, and separate setup and live pages. Run a scenario by id to stream Rich
events in the terminal; use `--no-live` for plain lines or `--json` for JSON:

```bash
uv run lab simulate
uv run lab simulate list
uv run lab simulate run reference-disputes
uv run lab simulate run reference-disputes --no-live
uv run lab simulate run reference-disputes --json
```

See `docs/user-simulator.md` for the timeline UI, the persistent-event
privacy contract, and the generic flow-plugin seam.

## Quality gate

Run the same checks used by CI:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

Database integration tests use the configured `DATABASE_URL`. GitHub Actions
provides a disposable PostgreSQL service, so CI does not use Neon credentials
or a shared production database.
