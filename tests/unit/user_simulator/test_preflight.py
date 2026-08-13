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
        "db_port": 5433,
        "db_name": "lab",
        "migration_command": None,
        "migration_profile": "lab-test-pg",
        "isolation_policy": "transaction-rollback",
        "artifact_root": "artifacts/user-simulator",
        "model_provider": None,
        "model_name": None,
        "required_variables": ("LAB_TEST_PG_URL", "MODEL_API_KEY"),
    },
)()


def test_resolve_runtime_uses_the_selected_profile_url() -> None:
    env = {"LAB_TEST_PG_URL": "postgresql://lab:lab@127.0.0.1:5433/lab"}
    runtime, issues = resolve_runtime(PROFILE, env)
    assert issues == ()
    assert runtime.database_url == "postgresql://lab:lab@127.0.0.1:5433/lab"
    assert runtime.environment == "test"
    assert runtime.isolation_policy == "transaction-rollback"
    assert runtime.artifact_root == "artifacts/user-simulator"


def test_resolve_runtime_refuses_mismatched_host_port_or_db() -> None:
    cases = {
        "postgresql://db.example.com:5433/lab": "host",
        "postgresql://127.0.0.1:9999/lab": "port",
        "postgresql://127.0.0.1:5433/other": "database",
    }
    for url, marker in cases.items():
        _, issues = resolve_runtime(PROFILE, {"LAB_TEST_PG_URL": url})
        assert issues, url
        assert marker in issues[0].message or marker in issues[0].fix


def test_resolve_runtime_refuses_non_loopback() -> None:
    _, issues = resolve_runtime(
        PROFILE, {"LAB_TEST_PG_URL": "postgresql://db.example.com:5433/lab"}
    )
    assert any("loopback" in issue.message for issue in issues)


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


async def test_preflight_rejects_unregistered_plugin_and_wrong_environment() -> None:
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
    assert "environment" in joined


async def _ok_probe(
    profile: object, env: object, cwd: object
) -> list[object]:
    del profile, env, cwd
    return []
