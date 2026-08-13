"""Evaluate the deterministic Phase 6 grouping baseline."""

import argparse
import json
from pathlib import Path

from app.domain.failures.dataset import load_failure_dataset
from app.domain.failures.features import extract_candidates
from app.domain.failures.grouping import group_candidates


def build_artifact(dataset_id: str = "failure_traces_v1") -> dict[str, object]:
    dataset = load_failure_dataset()
    if dataset.manifest.dataset_id != dataset_id:
        raise ValueError(f"unknown failure dataset {dataset_id!r}")
    candidates = extract_candidates(
        dataset.traces, dataset_version=dataset.manifest.dataset_version
    )
    result = group_candidates(
        candidates,
        dataset_id=dataset.manifest.dataset_id,
        dataset_version=dataset.manifest.dataset_version,
    )
    return {
        "schema_version": "1.0.0",
        "dataset_id": dataset.manifest.dataset_id,
        "dataset_version": dataset.manifest.dataset_version,
        "algorithm_version": result.algorithm_version,
        "configuration": result.configuration,
        "metrics": result.metrics.model_dump(mode="json"),
        "groups": [
            {
                "group_id": str(group_id),
                "members": [
                    {
                        "candidate_id": str(candidate.candidate_id),
                        "evidence_id": str(candidate.evidence_id),
                        "predicted_kind": candidate.predicted_kind.value,
                        "features": candidate.features,
                        "evidence_event_ids": candidate.evidence_event_ids,
                    }
                    for candidate in group
                ],
            }
            for group_id, group in zip(result.stable_group_ids, result.groups, strict=True)
        ],
        "outliers": [
            {
                "candidate_id": str(candidate.candidate_id),
                "evidence_id": str(candidate.evidence_id),
                "predicted_kind": candidate.predicted_kind.value,
                "features": candidate.features,
                "evidence_event_ids": candidate.evidence_event_ids,
            }
            for candidate in result.outliers
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate failure grouping baseline")
    parser.add_argument("--dataset", default="failure_traces_v1")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    artifact = build_artifact(arguments.dataset)
    output = arguments.output or Path("artifacts") / "failure-grouping-v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "metrics": artifact["metrics"]}, sort_keys=True))


if __name__ == "__main__":
    main()
