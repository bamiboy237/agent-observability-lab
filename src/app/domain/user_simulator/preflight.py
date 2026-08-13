"""Generic setup preflight for the user-simulator wizard.

Validates, before any run artifact exists: registered plugin, ENVIRONMENT,
required environment variables, the exact configured model, database
reachability/migrations (loopback disposable DB only), and a writable
artifact directory.  Every missing item gets one plain fix command/message.
Secret values are never read for display: only variable *presence* is
checked and the database URL is never printed.

This module is generic: it depends only on the environment-profile shape and
the flow registry.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from app.domain.user_simulator.flows import FlowRegistry, RuntimeEnvironment

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@runtime_checkable
class EnvironmentProfileLike(Protocol):
    """The environment-profile fields the preflight reads."""

    profile_id: str
    label: str
    environment: str
    loopback_only: bool
    db_url_env: str
    db_host: str | None
    db_port: int | None
    db_name: str | None
    migration_command: str | None
    migration_profile: str | None
    isolation_policy: str
    artifact_root: str
    model_provider: str | None
    model_name: str | None
    required_variables: tuple[str, ...]


# YAML stores only a migration *profile id*; the command lives in code.
MIGRATION_COMMANDS = {"local": "uv run alembic upgrade head"}


def _migration_fix(profile: EnvironmentProfileLike) -> str:
    if profile.migration_command:
        return profile.migration_command
    return MIGRATION_COMMANDS.get(
        profile.migration_profile or "",
        f"apply migrations for profile {profile.migration_profile!r}",
    )


@dataclass(frozen=True)
class PreflightIssue:
    """One preflight problem with a safe message and a plain fix command."""

    name: str
    message: str
    fix: str

    def __str__(self) -> str:
        return f"{self.name}: {self.message} — fix: {self.fix}"


DatabaseProbe = Callable[
    [EnvironmentProfileLike, Mapping[str, str], Path],
    Coroutine[object, object, list[PreflightIssue]],
]


def _missing_fix(name: str) -> str:
    fixes = {
        "DATABASE_URL": (
            "copy .env.example to .env and set DATABASE_URL to the disposable "
            "local lab-test database (loopback only)"
        ),
        "LAB_TEST_PG_URL": (
            "export LAB_TEST_PG_URL=<local disposable database URL> "
            "(never put credentials in the command)"
        ),
        "MODEL_PROVIDER": "set MODEL_PROVIDER=openai in .env",
        "MODEL_NAME": "set MODEL_NAME=gpt-5.6-luna in .env",
        "MODEL_API_KEY": "add your reviewed model API key to .env as MODEL_API_KEY",
    }
    return fixes.get(name, f"set {name} in .env (see .env.example)")


def _artifact_issue(profile: EnvironmentProfileLike, cwd: Path) -> PreflightIssue | None:
    root = Path(profile.artifact_root)
    if not root.is_absolute():
        root = cwd / root
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".simulator-write-probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return PreflightIssue(
            "artifacts",
            f"artifact directory {profile.artifact_root} is not writable "
            f"({type(error).__name__})",
            f"mkdir -p {profile.artifact_root} and check permissions",
        )
    return None


def _database_url(
    profile: EnvironmentProfileLike, env: Mapping[str, str]
) -> tuple[str | None, list[PreflightIssue]]:
    """Resolve the profile's database URL and refuse unsafe/mismatched values.

    The URL value itself is never part of any issue message.
    """
    issues: list[PreflightIssue] = []
    raw = env.get(profile.db_url_env)
    if not raw:
        return None, issues  # presence is reported by the required-variable check
    url = raw.replace("postgresql+asyncpg://", "postgresql://")
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or 5432
    database = (parts.path or "").lstrip("/")
    label = profile.db_url_env
    if profile.loopback_only and host not in _LOOPBACK_HOSTS:
        issues.append(
            PreflightIssue(
                "database",
                f"{label} host {host!r} is not loopback",
                "point the profile database URL at a disposable local database",
            )
        )
    if profile.db_host is not None and host != profile.db_host:
        issues.append(
            PreflightIssue(
                "database",
                f"{label} host {host!r} does not match profile {profile.profile_id}",
                f"set {label} host to {profile.db_host}",
            )
        )
    if profile.db_port is not None and port != profile.db_port:
        issues.append(
            PreflightIssue(
                "database",
                f"{label} port {port} does not match profile {profile.profile_id}",
                f"set {label} port to {profile.db_port}",
            )
        )
    if profile.db_name is not None and database != profile.db_name:
        issues.append(
            PreflightIssue(
                "database",
                f"{label} database {database!r} does not match profile "
                f"{profile.profile_id}",
                f"set {label} database to {profile.db_name}",
            )
        )
    return url, issues


def resolve_runtime(
    profile: EnvironmentProfileLike, env: Mapping[str, str]
) -> tuple[RuntimeEnvironment, tuple[PreflightIssue, ...]]:
    """Build the secret-safe runtime for the selected profile.

    Callers must refuse to start when the returned issues are non-empty: the
    selected profile URL must be loopback and must match the declared
    host/port/database.
    """
    url, issues = _database_url(profile, env)
    runtime = RuntimeEnvironment(
        environment=profile.environment,
        database_url=url,
        isolation_policy=profile.isolation_policy,
        artifact_root=profile.artifact_root,
    )
    return runtime, tuple(issues)


async def _probe_database(
    profile: EnvironmentProfileLike,
    env: Mapping[str, str],
    cwd: Path,
) -> list[PreflightIssue]:
    """Check DB host constraints, reachability, and migration head."""
    del cwd
    url, issues = _database_url(profile, env)
    if issues or url is None:
        return issues  # presence/constraint problems are reported already
    try:
        import asyncpg  # type: ignore[import-untyped]

        connection = await asyncpg.connect(dsn=url, timeout=4)
    except Exception as error:
        issues.append(
            PreflightIssue(
                "database",
                f"cannot connect to the test database ({type(error).__name__})",
                "start the disposable database: docker compose up -d lab-test-pg",
            )
        )
        return issues
    try:
        version = await connection.fetchval("SELECT version_num FROM alembic_version")
    except Exception:
        issues.append(
            PreflightIssue(
                "migrations",
                "alembic_version table not found; migrations are not applied",
                _migration_fix(profile),
            )
        )
        return issues
    finally:
        await connection.close()
    head = _migration_head()
    if head is not None and version != head:
        issues.append(
            PreflightIssue(
                "migrations",
                f"database is at migration {version}, head is {head}",
                _migration_fix(profile),
            )
        )
    return issues


def _migration_head() -> str | None:
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(AlembicConfig("alembic.ini"))
        return script.get_current_head()
    except Exception:
        return None


async def run_preflight(
    *,
    plugin_id: str,
    registry: FlowRegistry,
    profile: EnvironmentProfileLike,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    db_probe: DatabaseProbe | None = None,
) -> tuple[PreflightIssue, ...]:
    """Validate everything the run needs; returns an empty tuple when ready.

    Async so the database probe runs inside the caller's event loop; the CLI
    boundary owns the loop.
    """
    values: Mapping[str, str] = dict(env or {})
    root = Path(cwd or Path.cwd())
    issues: list[PreflightIssue] = []
    if not registry.contains(plugin_id):
        issues.append(
            PreflightIssue(
                "plugin",
                f"plugin {plugin_id!r} is not registered",
                "register the plugin through the flow registry before running",
            )
        )
    if values.get("ENVIRONMENT") != "test":
        issues.append(
            PreflightIssue(
                "environment",
                f"ENVIRONMENT must be 'test' (found {values.get('ENVIRONMENT')!r})",
                "export ENVIRONMENT=test or set it in .env",
            )
        )
    for name in profile.required_variables:
        if not values.get(name):
            issues.append(
                PreflightIssue(
                    "env." + name,
                    f"required environment variable {name} is not set",
                    _missing_fix(name),
                )
            )
    if profile.model_provider is not None:
        actual = values.get("MODEL_PROVIDER")
        if actual != profile.model_provider:
            issues.append(
                PreflightIssue(
                    "model",
                    f"MODEL_PROVIDER is {actual!r}, profile requires "
                    f"{profile.model_provider!r}",
                    f"set MODEL_PROVIDER={profile.model_provider} in .env",
                )
            )
    if profile.model_name is not None:
        actual = values.get("MODEL_NAME")
        if actual != profile.model_name:
            issues.append(
                PreflightIssue(
                    "model",
                    f"MODEL_NAME is {actual!r}, profile requires {profile.model_name!r}",
                    f"set MODEL_NAME={profile.model_name} in .env",
                )
            )
    writable = _artifact_issue(profile, root)
    if writable is not None:
        issues.append(writable)
    probe = db_probe if db_probe is not None else _probe_database
    issues.extend(await probe(profile, values, root))
    return tuple(issues)
