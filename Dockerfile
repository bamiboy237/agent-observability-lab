FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /workspace

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY alembic.ini .env.example ./
COPY alembic ./alembic
COPY config ./config
COPY simulations ./simulations
COPY src ./src
COPY tests ./tests

ENV PATH="/workspace/.venv/bin:$PATH"

CMD ["uv", "run", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
