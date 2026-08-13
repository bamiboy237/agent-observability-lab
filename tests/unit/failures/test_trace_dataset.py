"""Checkpoint 6.1 tests for the versioned canonical failure dataset."""

from app.domain.failures.dataset import load_failure_dataset, regenerate_manifest
from app.domain.failures.schemas import FailureKind


def test_dataset_is_versioned_and_contains_success_and_every_failure_kind() -> None:
    dataset = load_failure_dataset()
    labels = {item.label for item in dataset.manifest.labels if item.label is not None}
    assert labels == set(FailureKind)
    assert any(item.label is None for item in dataset.manifest.labels)
    assert dataset.manifest.trace_schema_version == "3.0.0"


def test_dataset_regeneration_matches_committed_manifest() -> None:
    generated = regenerate_manifest()
    dataset = load_failure_dataset()
    assert generated["content_hash"] == dataset.manifest.content_hash
