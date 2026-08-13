"""Deterministic, leakage-safe regression dataset manifests.

A source trace family must stay in one split. This prevents versions or cases
derived from the same observed conversation from appearing in both training
and evaluation data.
"""

import json
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.regression.schemas import RegressionCase

DATASET_MANIFEST_SCHEMA_VERSION = "1.0.0"


class DatasetCaseRef(BaseModel):
    """One immutable regression case version included in a dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    case_version: int = Field(ge=1)
    source_family: str = Field(min_length=1)


class RegressionDatasetManifest(BaseModel):
    """A versioned deterministic train/evaluation split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = DATASET_MANIFEST_SCHEMA_VERSION
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    dataset_version: int = Field(ge=1)
    split_seed: str = Field(min_length=1, max_length=200)
    evaluation_fraction: float = Field(gt=0, lt=1)
    train: tuple[DatasetCaseRef, ...]
    evaluation: tuple[DatasetCaseRef, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_no_leakage(self) -> "RegressionDatasetManifest":
        train_families = {item.source_family for item in self.train}
        evaluation_families = {item.source_family for item in self.evaluation}
        overlap = sorted(train_families & evaluation_families)
        if overlap:
            raise ValueError(f"source families occur in both splits: {overlap!r}")
        refs = [(item.case_id, item.case_version) for item in (*self.train, *self.evaluation)]
        if len(refs) != len(set(refs)):
            raise ValueError("a case version occurs more than once in the manifest")
        return self


def source_family(case: RegressionCase) -> str:
    """Return the stable source family used to prevent evaluation leakage."""
    source = case.evidence_ref
    if source is None:
        return f"designed:{case.case_id}"
    project = source.project or "-"
    return f"{source.platform}:{project}:{source.trace_id}"


def build_dataset_manifest(
    cases: list[RegressionCase] | tuple[RegressionCase, ...],
    *,
    dataset_id: str,
    dataset_version: int,
    split_seed: str,
    evaluation_fraction: float = 0.2,
) -> RegressionDatasetManifest:
    """Group immutable cases by source family and assign each family once."""
    if not 0 < evaluation_fraction < 1:
        raise ValueError("evaluation_fraction must be between zero and one")

    train: list[DatasetCaseRef] = []
    evaluation: list[DatasetCaseRef] = []
    ordered = sorted(cases, key=lambda case: (str(case.case_id), case.case_version))
    for case in ordered:
        family = source_family(case)
        digest = sha256(f"{split_seed}:{family}".encode()).digest()
        score = int.from_bytes(digest[:8], "big") / 2**64
        target = evaluation if score < evaluation_fraction else train
        target.append(
            DatasetCaseRef(
                case_id=str(case.case_id),
                case_version=case.case_version,
                source_family=family,
            )
        )

    payload = {
        "schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "split_seed": split_seed,
        "evaluation_fraction": evaluation_fraction,
        "train": [item.model_dump(mode="json") for item in train],
        "evaluation": [item.model_dump(mode="json") for item in evaluation],
    }
    content_hash = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return RegressionDatasetManifest(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        split_seed=split_seed,
        evaluation_fraction=evaluation_fraction,
        train=tuple(train),
        evaluation=tuple(evaluation),
        content_hash=content_hash,
    )
