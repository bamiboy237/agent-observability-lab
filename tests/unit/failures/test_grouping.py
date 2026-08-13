"""Checkpoint 6.4 tests for the deterministic grouping baseline."""

from app.domain.failures.dataset import load_failure_dataset
from app.domain.failures.features import extract_candidates
from app.domain.failures.grouping import group_candidates, normalize_features


def test_grouping_is_stable_when_candidate_order_changes() -> None:
    dataset = load_failure_dataset()
    candidates = extract_candidates(dataset.traces, dataset_version=1)
    first = group_candidates(candidates, min_samples=1)
    second = group_candidates(tuple(reversed(candidates)), min_samples=1)
    assert first.stable_group_ids == second.stable_group_ids
    assert tuple(item.evidence_id for item in first.outliers) == tuple(
        item.evidence_id for item in second.outliers
    )
    assert normalize_features(candidates) == normalize_features(tuple(reversed(candidates)))


def test_grouping_exposes_explicit_outliers_and_metrics() -> None:
    dataset = load_failure_dataset()
    candidates = extract_candidates(dataset.traces, dataset_version=1)
    result = group_candidates(candidates)
    assert result.metrics.candidate_count == len(candidates)
    assert result.metrics.grouped_candidate_count + result.metrics.outlier_count == len(candidates)
    assert result.algorithm_version == "deterministic-dbscan-v1"
