"""Checkpoint 6.3 tests for explainable candidate extraction."""

from app.domain.failures.dataset import load_failure_dataset
from app.domain.failures.features import extract_failure_candidate


def test_candidates_match_labeled_fixture_kinds_and_resolve_event_ids() -> None:
    dataset = load_failure_dataset()
    for evidence, label in zip(dataset.traces, dataset.manifest.labels, strict=True):
        candidate = extract_failure_candidate(evidence, dataset_version=1)
        if label.label is None:
            assert candidate is None
            continue
        assert candidate is not None
        assert candidate.predicted_kind is label.label
        event_ids = {event.event_id for event in evidence.events}
        assert set(candidate.evidence_event_ids) <= event_ids


def test_infrastructure_features_are_named_and_traceable() -> None:
    dataset = load_failure_dataset()
    evidence = next(
        item for item in dataset.traces if item.source.trace_id == "phase2-03-database-timeout"
    )
    candidate = extract_failure_candidate(evidence)
    assert candidate is not None
    assert candidate.features["retry_count"] == 1
    assert candidate.features["db_error_code"] == "timeout"
