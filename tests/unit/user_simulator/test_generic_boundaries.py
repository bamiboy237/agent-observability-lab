"""Decoupling proof: the generic CLI/viewer never depends on built-ins.

These tests guard the architecture: ``app.cli.simulate`` and the generic
event/flow modules import only the generic contract; the 15 built-in
support/reference plugins are optional adapters, not part of the CLI.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.cli import simulate
from app.domain.user_simulator.flows import FlowRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]

_GENERIC_FILES = (
    REPO_ROOT / "src/app/cli/simulate.py",
    REPO_ROOT / "src/app/domain/user_simulator/flows.py",
    REPO_ROOT / "src/app/domain/user_simulator/events.py",
)

# Modules that would tie the generic layer to the built-in cases.
_BUILTIN_SPECIFIC = (
    "app.domain.support",
    "app.domain.reference",
    "app.domain.user_simulator.personas",
    "app.domain.user_simulator.plugins",
    "app.domain.user_simulator.simulator",
)


def _imported_module_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_generic_cli_and_event_modules_never_import_builtin_specific_code() -> None:
    for path in _GENERIC_FILES:
        source = path.read_text()
        for module in _BUILTIN_SPECIFIC:
            assert module not in source, f"{path.name} must not reference {module}"
        # No hardcoded case ids or tool names either.
        assert "phase2-01-bad-prompt-policy-answer" not in source
        assert "reference-disputes" not in source
        assert "get_order_status" not in source
        assert "search_flights" not in source


def test_generic_cli_imports_and_runs_without_builtin_adapters(tmp_path: Path) -> None:
    """The CLI must import and run even if support/reference adapters are removed."""
    (tmp_path / "simulations").mkdir()
    script = textwrap.dedent(
        f"""
        import builtins

        BLOCKED = (
            "app.domain.support",
            "app.domain.reference",
            "app.domain.user_simulator.personas",
            "app.domain.user_simulator.plugins",
            "app.domain.user_simulator.simulator",
        )
        real_import = builtins.__import__

        def guarded(name, *args, **kwargs):
            if any(name == block or name.startswith(block + ".") for block in BLOCKED):
                raise ModuleNotFoundError(f"blocked: {{name}}")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = guarded

        import argparse

        from app.cli.simulate import build_simulate_parser, run_simulate
        from app.domain.user_simulator.flows import FlowRegistry

        parser = argparse.ArgumentParser()
        build_simulate_parser(parser, FlowRegistry())
        code = run_simulate(
            ["simulate", "list"],
            registry=FlowRegistry(),
            live=False,
            catalog_root="{tmp_path / 'simulations'}",
        )
        assert code == 0
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={"PYTHONPATH": str(REPO_ROOT / "src")},
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_empty_catalog_renders_a_clear_no_flows_state(tmp_path: Path, capsys) -> None:
    (tmp_path / "simulations").mkdir()
    registry = FlowRegistry()
    code = simulate.run_simulate(
        ["simulate", "list"],
        registry=registry,
        live=False,
        catalog_root=tmp_path / "simulations",
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "no simulations configured" in captured.out

    # An unknown simulation on an empty catalog names the problem clearly.
    with pytest.raises(SystemExit) as excinfo:
        simulate.run_simulate(
            ["simulate", "run", "anything"],
            registry=registry,
            live=False,
            catalog_root=tmp_path / "simulations",
        )
    assert excinfo.value.code == 1
    assert "simulation_not_found" in capsys.readouterr().err


def test_builtin_plugins_arrive_only_through_the_registry_seam() -> None:
    """A caller fills the registry with any plugins; built-ins are one option."""
    from app.domain.user_simulator.flows import FlowRegistrationError
    from app.domain.user_simulator.plugins import builtin_plugin_factory

    registry = FlowRegistry()
    assert len(registry) == 0
    for plugin in builtin_plugin_factory():
        registry.register(plugin)
    assert len(registry) == 15
    # Duplicate registration through the same seam fails loudly.
    with pytest.raises(FlowRegistrationError, match="duplicate flow id"):
        registry.register(builtin_plugin_factory()[0])
