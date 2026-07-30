# Agent Reliability Lab

A customer-support agent and reliability backend that turns selected traces into
reviewed failure groups, regression cases, deterministic replays, and
evidence-backed recommendations.

## Local setup

Requirements: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and a PostgreSQL
database. This workspace is linked to Neon, so authenticated contributors can
pull the current development branch configuration:

```bash
neon env pull --file .env
uv sync --frozen
uv run alembic upgrade head
```

Start the API:

```bash
uv run uvicorn app.main:create_app --factory
```

Then verify liveness and database readiness:

```bash
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

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
