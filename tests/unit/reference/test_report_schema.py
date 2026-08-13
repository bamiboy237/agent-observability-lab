"""This module tests the Phase 7.6 report schema versioning.

The report schema changed its persisted field names in Round 3 (setup-time
fields became run-duration and setup-effort fields), so the schema version
must be 2.0.0 and the serialized report must carry the new fields.
"""

from app.domain.reference.report import (
    REFERENCE_REPORT_SCHEMA_VERSION,
    ReferenceWorkflowReport,
    WorkflowEntry,
)
from app.domain.reference.runner import ReferenceRun


def _minimal_run() -> ReferenceRun:
    return ReferenceRun(
        run_id="run-1",
        workflow_id="flight_booking",
        side="baseline",
        label="baseline",
        verdict="reproduced",
        outcome="completed",
        reason_code="booking_confirmed",
        business_outcome="booking_confirmed",
        final_state_hash="abc",
        completed_at="2026-08-13T00:00:00Z",
    )


def _minimal_entry() -> WorkflowEntry:
    return WorkflowEntry(
        workflow_id="flight_booking",
        name="Flight booking",
        source="test",
        run_duration_seconds=0.001,
        setup_effort_notes="documented, not timed",
        baseline=_minimal_run(),
        candidate=_minimal_run(),
        comparison=__import__(
            "app.domain.reference.compare", fromlist=["compare_reference_runs"]
        ).compare_reference_runs(
            workflow_id="flight_booking",
            change_type="confirmation_gate",
            baseline_label="gate-required",
            candidate_label="auto-confirm",
            baseline=_minimal_run(),
            candidate=_minimal_run(),
        ),
    )


def test_report_schema_version_is_2_0_0() -> None:
    assert REFERENCE_REPORT_SCHEMA_VERSION == "2.0.0"


def test_report_serializes_new_field_names() -> None:
    report = ReferenceWorkflowReport(
        generated_at="2026-08-13T00:00:00Z",
        workflows=(_minimal_entry(),),
        total_run_duration_seconds=0.002,
    )

    payload = report.model_dump(mode="json")

    assert payload["schema_version"] == "2.0.0"
    assert "setup_seconds" not in payload["workflows"][0]
    assert payload["workflows"][0]["run_duration_seconds"] == 0.001
    assert payload["workflows"][0]["setup_effort_notes"] == "documented, not timed"
    assert payload["total_run_duration_seconds"] == 0.002
    assert payload["workflows"][0]["baseline"]["tokens_are_estimates"] is True
    assert payload["workflows"][0]["baseline"]["cost_is_estimate"] is True
