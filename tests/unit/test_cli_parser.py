"""CLI parser tests for commands that must reject incomplete or unknown input."""

import pytest

from app.cli.main import build_parser


def test_run_requires_exactly_one_input_source() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["run"])
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "bundle.json", "--case", "case-id@1"])

    assert parser.parse_args(["run", "bundle.json"]).bundle_path == "bundle.json"
    assert parser.parse_args(["run", "--case", "case-id@1"]).case == "case-id@1"


@pytest.mark.parametrize("command", ["cases", "suites"])
def test_list_commands_reject_unknown_operations(command: str) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([command, "typo"])

    assert parser.parse_args([command, "list"]).func is not None


def test_simulate_defaults_and_programmatic_flags() -> None:
    parser = build_parser()

    default_run = parser.parse_args(["simulate"])
    assert default_run.simulate_command == "run"
    assert default_run.simulation_id is None

    explicit_run = parser.parse_args(
        ["simulate", "run", "phase2-03-database-timeout", "--max-turns", "5", "--yes"]
    )
    assert explicit_run.simulation_id == "phase2-03-database-timeout"
    assert explicit_run.max_turns == 5
    assert explicit_run.yes is True
