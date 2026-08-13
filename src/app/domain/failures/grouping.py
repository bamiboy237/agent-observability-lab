"""Small deterministic mixed-feature grouping baseline.

The baseline uses named scalar and categorical features only.  It does not
embed raw text and does not require a machine-learning dependency.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid5

from app.domain.failures.schemas import (
    FAILURE_GROUPING_ALGORITHM_VERSION,
    FailureCandidate,
    FailureGroupingMetrics,
    FailureGroupProposal,
    FailureGroupResult,
    ProposalStatus,
    content_hash,
)

GROUP_NAMESPACE = UUID("a1dd7ce4-1ca6-46b7-95f1-47b7bb4fbf01")


def normalize_features(
    candidates: Iterable[FailureCandidate],
) -> dict[UUID, tuple[tuple[str, str], ...]]:
    """Normalize booleans, numbers, and categories in sorted feature order.

    The output is intentionally inspectable. Numeric values retain their
    decimal representation; categorical values retain their labels.
    """
    return {
        candidate.candidate_id: tuple(
            (name, _normalized_value(value)) for name, value in sorted(candidate.features.items())
        )
        for candidate in sorted(candidates, key=lambda item: str(item.candidate_id))
    }


def _normalized_value(value: bool | int | float | str) -> str:
    if isinstance(value, bool):
        return "bool:1" if value else "bool:0"
    if isinstance(value, (int, float)):
        return f"number:{float(value):.12g}"
    return f"category:{value}"


def _distance(first: FailureCandidate, second: FailureCandidate) -> float:
    names = sorted(set(first.features) | set(second.features))
    if not names:
        return 0.0
    total = 0.0
    for name in names:
        left = first.features.get(name)
        right = second.features.get(name)
        if left is None or right is None:
            total += 1.0
        elif (
            isinstance(left, (int, float))
            and not isinstance(left, bool)
            and isinstance(right, (int, float))
            and not isinstance(right, bool)
        ):
            scale = max(1.0, abs(float(left)), abs(float(right)))
            total += min(1.0, abs(float(left) - float(right)) / scale)
        else:
            total += 0.0 if left == right else 1.0
    return total / len(names)


def group_candidates(
    candidates: Iterable[FailureCandidate],
    *,
    dataset_id: str = "failure_traces_v1",
    dataset_version: int = 1,
    epsilon: float = 0.2,
    min_samples: int = 2,
) -> FailureGroupResult:
    """Group candidates with an order-independent DBSCAN-style baseline."""
    if epsilon < 0:
        raise ValueError("epsilon must be non-negative")
    if min_samples < 1:
        raise ValueError("min_samples must be positive")
    ordered = tuple(sorted(candidates, key=lambda item: str(item.candidate_id)))
    neighbours: dict[UUID, tuple[UUID, ...]] = {
        candidate.candidate_id: tuple(
            other.candidate_id for other in ordered if _distance(candidate, other) <= epsilon
        )
        for candidate in ordered
    }
    core_ids = {
        candidate_id
        for candidate_id, neighbour_ids in neighbours.items()
        if len(neighbour_ids) >= min_samples
    }
    by_id = {candidate.candidate_id: candidate for candidate in ordered}
    clusters: list[tuple[FailureCandidate, ...]] = []
    assigned: set[UUID] = set()
    for seed in sorted(core_ids, key=str):
        if seed in assigned:
            continue
        pending = [seed]
        members: set[UUID] = set()
        while pending:
            current = pending.pop(0)
            if current in members:
                continue
            members.add(current)
            if current in core_ids:
                pending.extend(sorted(neighbours[current], key=str))
        assigned.update(members)
        clusters.append(tuple(by_id[item] for item in sorted(members, key=str)))
    clusters.sort(key=lambda group: str(group[0].candidate_id))
    outliers = tuple(candidate for candidate in ordered if candidate.candidate_id not in assigned)
    group_ids = tuple(
        uuid5(
            GROUP_NAMESPACE,
            content_hash(
                {
                    "algorithm": FAILURE_GROUPING_ALGORITHM_VERSION,
                    "dataset": dataset_id,
                    "version": dataset_version,
                    "members": [str(item.candidate_id) for item in group],
                }
            ),
        )
        for group in clusters
    )
    grouped_count = sum(len(group) for group in clusters)
    metrics = FailureGroupingMetrics(
        candidate_count=len(ordered),
        grouped_candidate_count=grouped_count,
        outlier_count=len(outliers),
        group_count=len(clusters),
        coverage=grouped_count / len(ordered) if ordered else 0.0,
    )
    return FailureGroupResult(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        configuration={"epsilon": epsilon, "min_samples": min_samples},
        groups=tuple(clusters),
        outliers=outliers,
        stable_group_ids=group_ids,
        metrics=metrics,
    )


def _shared_features(group: tuple[FailureCandidate, ...]) -> dict[str, bool | int | float | str]:
    shared = dict(group[0].features)
    for candidate in group[1:]:
        shared = {
            name: value for name, value in shared.items() if candidate.features.get(name) == value
        }
    return dict(sorted(shared.items()))


def proposals_from_result(
    result: FailureGroupResult,
    *,
    created_at: datetime | None = None,
) -> tuple[FailureGroupProposal, ...]:
    """Convert grouped candidates into reviewable, provenance-rich proposals."""
    timestamp = created_at or datetime.now(UTC)
    proposals: list[FailureGroupProposal] = []
    for group_id, group in zip(result.stable_group_ids, result.groups, strict=True):
        evidence_ids = tuple(sorted({candidate.evidence_id for candidate in group}, key=str))
        evidence_event_ids = {
            str(candidate.evidence_id): candidate.evidence_event_ids
            for candidate in sorted(group, key=lambda item: str(item.evidence_id))
        }
        payload = {
            "dataset_id": result.dataset_id,
            "dataset_version": result.dataset_version,
            "algorithm_version": result.algorithm_version,
            "predicted_kind": group[0].predicted_kind.value,
            "candidate_ids": sorted(str(candidate.candidate_id) for candidate in group),
            "evidence_ids": sorted(str(item) for item in evidence_ids),
            "shared_features": _shared_features(group),
        }
        fingerprint = content_hash(payload)
        proposal_id = uuid5(GROUP_NAMESPACE, f"proposal:{fingerprint}")
        proposals.append(
            FailureGroupProposal(
                proposal_id=proposal_id,
                group_id=group_id,
                proposal_fingerprint=fingerprint,
                dataset_id=result.dataset_id,
                dataset_version=result.dataset_version,
                algorithm_version=result.algorithm_version,
                predicted_kind=group[0].predicted_kind,
                candidate_ids=tuple(sorted((item.candidate_id for item in group), key=str)),
                evidence_ids=evidence_ids,
                evidence_event_ids=evidence_event_ids,
                shared_features=_shared_features(group),
                status=ProposalStatus.PROPOSED,
                created_at=timestamp,
            )
        )
    return tuple(proposals)


__all__ = ["group_candidates", "normalize_features", "proposals_from_result"]
