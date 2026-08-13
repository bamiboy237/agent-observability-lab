# Repository Guidelines

## User Updates

Treat the user as a product manager who needs clear, short progress updates.

- Send a short update before you start work.
- For work that takes more than one minute, send another update at least every 60 seconds.
- State the goal, the work you completed, why it matters, and your next step.
- Use plain English. Avoid jargon and unexplained technical terms.
- Do not use terms such as "smoke test," "config guarded," "load bearing," or "core" without explanation.
- Replace technical labels with direct descriptions of what the system does.
- Keep each update to two to four short sentences unless the user asks for more detail.
- Do not paste raw logs. Summarize the result and include only useful error details.
- State clearly when you make an assumption, encounter a problem, or need user input.
- At completion, report the changed files, checks that passed, checks that you skipped, and any remaining risk.

## Project Structure & Module Organization

Application code lives in `src/app/`. Put FastAPI routes in `src/app/api/` and
business rules in `src/app/domain/`. Store migrations in `alembic/versions/`
and operational scripts in `scripts/`.

Use `tests/unit/` for pure behavior, `tests/integration/` for PostgreSQL-backed
behavior, and `tests/fakes/` for focused test doubles. Read `BUILD_ROADMAP.md`
before product work and preserve its phase boundaries.

## Build, Test, and Development Commands

- `uv sync --frozen` installs the locked Python 3.12 environment.
- `uv run alembic upgrade head` applies database migrations.
- `uv run python scripts/seed.py` loads idempotent support fixtures.
- `uv run uvicorn app.main:create_app --factory` starts the local API.
- `uv run ruff check .` checks formatting and imports.
- `uv run mypy src` runs strict type checking.
- `uv run pytest tests/unit -q` runs fast offline tests.
- `uv run pytest` runs the full suite against an isolated database.

Run migration and integration tests only against disposable PostgreSQL or an
isolated Neon branch.

## Coding Style & Naming Conventions

Use four-space indentation, complete type annotations, and a 100-character
line limit. Ruff enforces `E`, `F`, and `I`; mypy is strict. Use `snake_case`
for modules and functions, `PascalCase` for classes, and
`test_<observable_behavior>` for tests. Keep routes thin. Enforce authorization,
policy, confirmation, and state transitions in domain services—not prompts.

## Testing Guidelines

Use pytest and `pytest-asyncio`. Add only tests needed at a stable
boundary. Python unit tests may mock the hosted-model boundary to verify
behavior and parsing without network calls. Keep mocks small and specific to
the test; do not create a production workflow around a fake model. Live and
end-to-end agent checks must use the real hosted
model. Credential-gated model and telemetry tests must skip when
settings are absent.

## Commit & Pull Request Guidelines

Follow the history’s short imperative style, such as `Add support HTTP API`.
Keep commits scoped. Do not commit `.env`, secrets, caches, or unrelated files.
Report changed files, checks, skipped live checks, and manual review steps;
commit and push only after user confirmation.

Pull requests must explain behavior, risk, configuration or migration impact,
and verification. Include screenshots only for visible UI changes. Link the
roadmap phase or issue when one exists.

## Security & Configuration

Copy `.env.example` to `.env` and keep credentials local. Traces must use
allowlisted attributes and must never contain secrets, unrestricted user text,
or private database state. External model and observability integrations must
remain optional and fail safely when incomplete.
