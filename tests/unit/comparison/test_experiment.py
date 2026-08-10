"""This module tests the one-variable experiment contract (checkpoint 6.5).

An experiment changes exactly one major dimension — model, prompt, retrieval,
tools, workflow, routing, or policy — and rejects hidden changes, multiple
changes, and missing versions. Every configuration version and the bundle
identifier are recorded.
"""

import pytest
from pydantic import ValidationError

from app.domain.bundle.schemas import ConfigurationVersions, SimulationBundle
from app.domain.comparison.experiment import (
    ConfigurationChangeType,
    ConfigurationSet,
    validate_baseline_matches_bundle,
)
from app.domain.simulation.adapters import CoverageItem
from app.domain.simulation.scenarios import SCENARIO_BY_ID

COVERAGE_ITEMS = (
    CoverageItem(
        dependency="support.database",
        kind="stateful",
        tools=("get_order_status", "get_policy", "propose_refund", "confirm_refund", "escalate"),
        state_transitions=("order:delivered->refunded", "ticket:created"),
    ),
)

REVIEW = {
    "approved_request_message": "Use the approved synthetic request for this simulation.",
    "reviewer": "alice",
    "reviewed_at": "2026-08-08T00:00:00Z",
    "reason": "Reviewed and approved",
    "review_status": "approved",
}


def make_baseline() -> ConfigurationVersions:
    return ConfigurationVersions(
        workflow="support_agent",
        workflow_version="2.0.0",
        routing_instructions_version="1",
        answer_instructions_version="1",
        model_provider="openai",
        model_name="gpt-5.2",
        policy_version=None,
        tool_versions={},
        configuration_version="2.0.0",
    )


def make_bundle() -> SimulationBundle:
    from app.domain.bundle.compiler import compile_bundle

    scenario = SCENARIO_BY_ID["phase2-08-model-cost-comparison"]
    return compile_bundle(
        scenario=scenario,
        evidence=None,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )


def make_policy_bundle() -> SimulationBundle:
    from app.domain.bundle.compiler import compile_bundle

    scenario = SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"]
    return compile_bundle(
        scenario=scenario,
        evidence=None,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )


def experiment(
    change_type: ConfigurationChangeType,
    candidate: ConfigurationVersions,
    bundle: SimulationBundle,
) -> ConfigurationSet:
    return ConfigurationSet(
        bundle_id=bundle.bundle_id or __import__("uuid").UUID(int=0),
        change_type=change_type,
        baseline=make_baseline(),
        candidate=candidate,
    )


def test_model_change_passes() -> None:
    bundle = make_bundle()
    candidate = make_baseline().model_copy(
        update={"model_name": "gpt-5.6", "model_provider": "openai"}
    )
    validated = experiment(ConfigurationChangeType.MODEL, candidate, bundle)
    assert validated.change_type is ConfigurationChangeType.MODEL
    assert validated.baseline.model_name == "gpt-5.2"
    assert validated.candidate.model_name == "gpt-5.6"


def test_prompt_change_passes() -> None:
    bundle = make_bundle()
    candidate = make_baseline().model_copy(update={"answer_instructions_version": "2"})
    experiment(ConfigurationChangeType.PROMPT, candidate, bundle)


def test_retrieval_change_passes() -> None:
    bundle = make_policy_bundle()
    baseline = make_baseline().model_copy(update={"policy_version": "2026-07-30"})
    candidate = baseline.model_copy(update={"policy_version": "2026-08-01"})
    validated = ConfigurationSet(
        bundle_id=bundle.bundle_id or __import__("uuid").UUID(int=0),
        change_type=ConfigurationChangeType.RETRIEVAL,
        baseline=baseline,
        candidate=candidate,
    )
    assert validated.candidate.policy_version == "2026-08-01"


def test_workflow_change_passes() -> None:
    bundle = make_bundle()
    candidate = make_baseline().model_copy(
        update={"workflow_version": "2.1.0", "configuration_version": "2.1.0"}
    )
    experiment(ConfigurationChangeType.WORKFLOW, candidate, bundle)


def test_routing_change_passes() -> None:
    bundle = make_bundle()
    candidate = make_baseline().model_copy(update={"routing_instructions_version": "2"})
    experiment(ConfigurationChangeType.ROUTING, candidate, bundle)


def test_tools_change_passes() -> None:
    bundle = make_bundle()
    candidate = make_baseline().model_copy(update={"tool_versions": {"get_order_status": "4.1.0"}})
    experiment(ConfigurationChangeType.TOOLS, candidate, bundle)


def test_policy_change_passes() -> None:
    bundle = make_policy_bundle()
    baseline = make_baseline().model_copy(update={"policy_version": "2026-07-30"})
    candidate = baseline.model_copy(update={"policy_version": "2026-09-01"})
    ConfigurationSet(
        bundle_id=bundle.bundle_id or __import__("uuid").UUID(int=0),
        change_type=ConfigurationChangeType.POLICY,
        baseline=baseline,
        candidate=candidate,
    )


def test_hidden_model_change_is_rejected() -> None:
    bundle = make_bundle()
    candidate = make_baseline().model_copy(
        update={"model_name": "gpt-5.6", "answer_instructions_version": "2"}
    )
    with pytest.raises(ValidationError, match="hidden change"):
        experiment(ConfigurationChangeType.MODEL, candidate, bundle)


def test_no_change_in_declared_dimension_is_rejected() -> None:
    bundle = make_bundle()
    candidate = make_baseline()
    with pytest.raises(ValidationError, match="no change in the declared dimension"):
        experiment(ConfigurationChangeType.PROMPT, candidate, bundle)


def test_missing_model_version_is_rejected() -> None:
    bundle = make_bundle()
    candidate = make_baseline().model_copy(update={"model_name": None, "model_provider": None})
    with pytest.raises(ValidationError, match="missing version"):
        experiment(ConfigurationChangeType.MODEL, candidate, bundle)


def test_baseline_must_equal_the_bundle_configuration() -> None:
    bundle = make_bundle()
    candidate = make_baseline().model_copy(update={"model_name": "gpt-5.6"})
    experiment_set = experiment(ConfigurationChangeType.MODEL, candidate, bundle)
    # The compiled bundle carries the scenario's declared model, so a baseline
    # that differs from it is a hidden edit.
    assert bundle.configuration_versions.model_name == "gpt-5.2"
    validate_baseline_matches_bundle(experiment_set, bundle)
    wrong = experiment_set.model_copy(
        update={"baseline": make_baseline().model_copy(update={"model_name": "gpt-4.1"})}
    )
    with pytest.raises(Exception, match="baseline configuration differs"):
        validate_baseline_matches_bundle(wrong, bundle)


def test_baseline_must_reference_the_same_bundle() -> None:
    from app.domain.bundle.compiler import compile_bundle

    bundle = make_bundle()
    other = compile_bundle(
        scenario=SCENARIO_BY_ID["phase2-03-database-timeout"],
        evidence=None,
        coverage_items=COVERAGE_ITEMS,
        **REVIEW,
    )
    candidate = make_baseline().model_copy(update={"model_name": "gpt-5.6"})
    experiment_set = experiment(ConfigurationChangeType.MODEL, candidate, other)
    with pytest.raises(Exception, match="does not match bundle"):
        validate_baseline_matches_bundle(experiment_set, bundle)
