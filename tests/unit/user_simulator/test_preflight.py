"""Focused tests for the setup preflight and runtime resolution."""

from __future__ import annotations

import re

from app.domain.user_simulator.flows import FlowRegistry
from app.domain.user_simulator.plugins import build_default_registry
from app.domain.user_simulator.preflight import (
    _missing_fix,
    resolve_runtime,
    run_preflight,
)

PROFILE = type(
    "Profile",
    (),
    {
        "profile_id": "lab-test-pg",
        "label": "Local",
        "environment": "test",
        "loopback_only": True,
        "db_url_env": "LAB_TEST_PG_URL",
        "db_host": "127.0.0.1",
        "db_port": 55433,
        "db_name": "lab",
        "isolation_policy": "transaction-rollback",
        "artifact_root": "artifacts/user-simulator",
        "model_provider": None,
        "model_name": None,
        "required_variables": ("LAB_TEST_PG_URL", "MODEL_API_KEY"),
    },
)()


def test_resolve_runtime_uses_the_selected_profile_url() -> None:
    env = {"LAB_TEST_PG_URL": "postgresql://lab:lab@127.0.0.1:55433/lab"}
    runtime, issues = resolve_runtime(PROFILE, env)
    assert issues == ()
    assert runtime.database_url == "postgresql://lab:lab@127.0.0.1:55433/lab"
    assert runtime.environment == "test"
    assert runtime.isolation_policy == "transaction-rollback"
    assert runtime.artifact_root == "artifacts/user-simulator"


def test_resolve_runtime_refuses_non_postgres_scheme() -> None:
    _, issues = resolve_runtime(
        PROFILE, {"LAB_TEST_PG_URL": "http://example.com/db"}
    )
    assert any("scheme" in issue.message for issue in issues)


def test_missing_fix_text_never_contains_credentials() -> None:
    for name in ("LAB_TEST_PG_URL", "DATABASE_URL", "MODEL_API_KEY"):
        fix = _missing_fix(name)
        # No credential-shaped sample (user:pass@host) and no real values.
        assert "://lab:lab" not in fix
        assert re.search(r"://[^/@\s:]+:[^/@\s]+@", fix) is None
        # A plain, non-empty instruction with no credential material.
        assert fix.strip()
        assert "://" not in fix.replace("<local disposable database URL>", "")


async def test_preflight_reports_each_missing_required_variable() -> None:
    registry = build_default_registry()
    issues = await run_preflight(
        plugin_id="phase2-01-bad-prompt-policy-answer",
        registry=registry,
        profile=PROFILE,
        env={"ENVIRONMENT": "test"},
        db_probe=_ok_probe,
    )
    names = {issue.name for issue in issues}
    assert "env.LAB_TEST_PG_URL" in names
    assert "env.MODEL_API_KEY" in names
    assert "plugin" not in names


async def test_preflight_rejects_unregistered_plugin() -> None:
    registry = FlowRegistry()
    issues = await run_preflight(
        plugin_id="unknown",
        registry=registry,
        profile=PROFILE,
        env={"ENVIRONMENT": "production"},
        db_probe=_ok_probe,
    )
    joined = " ".join(issue.name for issue in issues)
    assert "plugin" in joined


async def _ok_probe(
    profile: object, env: object, cwd: object
) -> list[object]:
    del profile, env, cwd
    return []
