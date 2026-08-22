# Simulate

Simulate creates isolated, resettable sandbox environments to test, investigate, and improve AI agents against realistic business workflows.

Simulate does not host or deploy customer agents in production. Instead, Simulate runs customer agents inside disposable sandboxes with sanitized database state and mock services. Teams use Simulate to reproduce production failures, test agent updates, and measure behavioral changes before releasing code to production.

## Current status

- **Phases 0–7 (Complete):** Core support domain, LangSmith and Braintrust trace ingestion, LangGraph stateful workflow checkpointing, isolated PostgreSQL provisioning, and the terminal user simulator.
- **Phase 8 MVP (In progress):** Runs Prime Agent (a coding harness by Prime Intellect) inside a detached Modal cloud sandbox. Prime Agent investigates production traces, reproduces issues, streams live events, and writes an immutable evidence summary.

For the detailed phase plan and architecture, see [`BUILD_ROADMAP.md`](file:///Users/king/Desktop/simulate/BUILD_ROADMAP.md) and [`ARCHITECTURE.md`](file:///Users/king/Desktop/simulate/ARCHITECTURE.md).

## Requirements

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- PostgreSQL (local or Neon)
- Docker (optional, for containerized local development)

## Quickstart

### 1. Configure the environment

To pull your development configuration when you use Neon:

```bash
neon env pull --file .env
```

If you do not use Neon, copy the example environment file and add your credentials:

```bash
cp .env.example .env
```

### 2. Install dependencies and apply migrations

Run the following commands to install dependencies and migrate the database:

```bash
uv sync --frozen
uv run alembic upgrade head
```

To load sample fixture data for local testing, run:

```bash
uv run python scripts/seed.py
```

### 3. Start the API server

Start the local FastAPI application:

```bash
uv run uvicorn app.main:create_app --factory
```

Verify that the server is healthy:

```bash
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

---

## Docker development

You can run PostgreSQL and the API server together with Docker Compose.

To build and start the containers:

```bash
docker compose up --build
```

The database binds to `127.0.0.1:55433` and persists data in a named Docker volume.

To run the test suite inside the Docker container:

```bash
docker compose --profile test run --rm test
```

To stop all containers and remove the database volume:

```bash
docker compose down -v
```

---

## User simulator CLI

The user simulator runs persona-driven test scenarios against target agents and streams events to your terminal.

To open the full-screen terminal interface:

```bash
uv run lab simulate
```

To list available simulation scenarios:

```bash
uv run lab simulate list
```

To run a specific scenario and view the event stream:

```bash
uv run lab simulate run reference-disputes
```

To output plain text or JSON instead of the rich UI:

```bash
uv run lab simulate run reference-disputes --no-live
uv run lab simulate run reference-disputes --json
```

For configuration details and privacy policies, see [`docs/user-simulator.md`](file:///Users/king/Desktop/simulate/docs/user-simulator.md).

---

## Quality checks

Run these checks before you push changes or open a pull request:

```bash
uv run ruff check .
uv run mypy src
uv run pytest tests/unit -q
uv run pytest
```

---

## Documentation

- [`ARCHITECTURE.md`](file:///Users/king/Desktop/simulate/ARCHITECTURE.md): System architecture, control plane versus execution plane, and sandbox lifecycle.
- [`BUILD_ROADMAP.md`](file:///Users/king/Desktop/simulate/BUILD_ROADMAP.md): Product roadmap, milestone acceptance criteria, and schema contracts.
- [`AGENTS.md`](file:///Users/king/Desktop/simulate/AGENTS.md): Coding style, testing rules, and commands for autonomous agents.
- [`docs/user-simulator.md`](file:///Users/king/Desktop/simulate/docs/user-simulator.md): Simulator setup, preflight checks, and event contracts.
