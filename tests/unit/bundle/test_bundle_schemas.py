"""This module tests the SimulationBundle schema for checkpoint 5.1.

The schema includes source references, a privacy-safe scenario, synthetic seeds,
expected behavior, configuration versions, dependency fixtures, adapter
versions, redaction decisions, coverage, and stable hashes. Representative
bundles round-trip without losing meaning, and the schema rejects unknown
fields, unapproved reviews, and identifiers that do not match the content.
"""

import pytest
from pydantic import ValidationError

from app.domain.bundle.errors import ForbiddenDataError
from app.domain.bundle.extract import synthetic_id
from app.domain.bundle.schemas import (
    BundleRequest,
    BundleScenario,
    ConfigurationVersions,
    CoverageInfo,
    ReviewDecision,
    ReviewStatus,
    SimulationBundle,
    compute_bundle_hash,
)
from app.domain.simulation.scenarios import SCENARIO_BY_ID


def _review(status: ReviewStatus = ReviewStatus.APPROVED) -> ReviewDecision:
    return ReviewDecision(
        status=status,
        reviewer="alice",
        reviewed_at="2026-08-08T00:00:00Z",
        reason="Expected behavior verified",
    )


def _bundle(review: ReviewDecision | None = None) -> SimulationBundle:
    scenario = SCENARIO_BY_ID["phase2-01-bad-prompt-policy-answer"]
    return SimulationBundle(
        scenario=BundleScenario(
            scenario_id=scenario.scenario_id,
            source_schema_version=scenario.schema_version,
            source_content_hash=scenario.content_hash or "a" * 64,
            category=scenario.category,
            request=BundleRequest(
                customer_id=synthetic_id(scenario.request.customer_id),
                message="Use the approved synthetic policy request.",
                refund_confirmed=False,
            ),
            workflow_context=scenario.workflow_context,
            eligible_actions=scenario.eligible_actions,
            required_dependency_coverage=scenario.required_dependency_coverage,
        ),
        evidence_ref={
            "platform": "langsmith",
            "project": "agent-reliability-lab",
            "trace_id": "phase2-01-bad-prompt-policy-answer",
        },
        evidence_content_hash="a" * 64,
        expected_behavior=scenario.expected_behavior,
        configuration_versions=ConfigurationVersions(),
        resource_seeds=(),
        dependency_fixtures=(),
        adapter_versions={},
        coverage=CoverageInfo(covered=(), missing=()),
        redaction_decisions=(),
        review=review or _review(),
    )


def test_bundle_round_trips_through_json() -> None:
    bundle = _bundle()
    restored = SimulationBundle.model_validate(bundle.model_dump(mode="json"))
    assert restored == bundle
    assert restored.schema_version == "1.0.0"
    assert restored.bundle_id == bundle.bundle_id
    assert restored.content_hash == bundle.content_hash


def test_bundle_derives_identifier_from_content() -> None:
    first = _bundle()
    second = _bundle()
    assert first.bundle_id is not None
    assert first.bundle_id == second.bundle_id
    assert len(str(first.bundle_id)) == 36


def test_bundle_rejects_unknown_top_level_field() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["vendor_secret_store"] = "do-not-copy"
    with pytest.raises(ValidationError, match="vendor_secret_store"):
        SimulationBundle.model_validate(payload)


def test_review_decision_supports_all_review_states() -> None:
    for status in ReviewStatus:
        review = ReviewDecision(
            status=status,
            reviewer="alice",
            reviewed_at="2026-08-08T00:00:00Z",
            reason="Expected behavior verified",
        )
        assert review.status is status


def test_bundle_rejects_unapproved_review() -> None:
    for status in (ReviewStatus.PENDING, ReviewStatus.REJECTED, ReviewStatus.SUPERSEDED):
        with pytest.raises(ValidationError, match="approved"):
            _bundle(review=_review(status))


def test_bundle_rejects_forbidden_resource_seed() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["resource_seeds"] = [
        {
            "resource": "order",
            "adapter_name": "support.database",
            "adapter_version": "4.0.0",
            "records": [{"id": "x", "customer_id": "y", "status": "delivered", "api_key": "z"}],
        }
    ]
    with pytest.raises(ForbiddenDataError, match="api_key"):
        SimulationBundle.model_validate(payload)


def test_bundle_rejects_secret_in_typed_metadata() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["review"]["source_evidence"] = "https://example.test/run?token=secret-value"
    payload["bundle_id"] = None
    payload["content_hash"] = None

    with pytest.raises(ForbiddenDataError, match="forbidden value"):
        SimulationBundle.model_validate(payload)


def test_bundle_rejects_forged_identifier() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["bundle_id"] = "12345678-1234-4234-8234-123456789abc"
    with pytest.raises(ValidationError, match="bundle id"):
        SimulationBundle.model_validate(payload)


def test_bundle_rejects_stale_content_hash() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["content_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="content hash"):
        SimulationBundle.model_validate(payload)


def test_bundle_hash_is_stable_and_content_sensitive() -> None:
    first = _bundle()
    second = _bundle()
    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64

    changed = first.model_copy(
        update={
            "scenario": first.scenario.model_copy(
                update={"scenario_id": "phase2-03-database-timeout"}
            )
        }
    )
    assert compute_bundle_hash(changed) != first.content_hash
