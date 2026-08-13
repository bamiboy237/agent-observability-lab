"""Dataset splits keep related source traces together and remain reproducible."""

from copy import deepcopy
from uuid import uuid4

from app.domain.bundle.compiler import compile_bundle
from app.domain.bundle.schemas import SimulationBundle
from app.domain.evidence.schemas import TraceSourceRef
from app.domain.regression.dataset import build_dataset_manifest
from app.domain.regression.schemas import CaseSourceType, RegressionCase
from app.domain.simulation.scenarios import SCENARIOS


def _case(*, trace_id: str, version: int) -> RegressionCase:
    scenario = SCENARIOS[0]
    bundle = compile_bundle(
        scenario=scenario,
        approved_request_message="Use the approved synthetic request for this dataset case.",
        reviewer="dataset-reviewer",
        reviewed_at="2026-08-13T00:00:00Z",
        reason="Approved for the deterministic dataset fixture.",
        review_status="approved",
    )
    payload = bundle.model_dump(mode="json", exclude={"bundle_id", "content_hash"})
    payload["evidence_ref"] = TraceSourceRef(
        platform="fixture", project="support", trace_id=trace_id
    ).model_dump(mode="json")
    bundle = SimulationBundle.model_validate(payload)
    return RegressionCase(
        case_id=uuid4(),
        case_version=version,
        source_type=CaseSourceType.INCIDENT,
        scenario_id=bundle.scenario.scenario_id,
        bundle=bundle,
        bundle_content_hash=bundle.content_hash,
        evidence_ref=bundle.evidence_ref,
        evidence_content_hash=bundle.evidence_content_hash,
        configuration_versions=bundle.configuration_versions,
        created_at="2026-08-13T00:00:00+00:00",
    )


def test_split_is_stable_and_keeps_trace_families_together() -> None:
    cases = [
        _case(trace_id="conversation-a", version=1),
        _case(trace_id="conversation-a", version=2),
        _case(trace_id="conversation-b", version=1),
        _case(trace_id="conversation-c", version=1),
    ]

    first = build_dataset_manifest(
        cases,
        dataset_id="failure_traces_v1",
        dataset_version=1,
        split_seed="reviewed-seed-v1",
        evaluation_fraction=0.5,
    )
    second = build_dataset_manifest(
        list(reversed(deepcopy(cases))),
        dataset_id="failure_traces_v1",
        dataset_version=1,
        split_seed="reviewed-seed-v1",
        evaluation_fraction=0.5,
    )

    assert first == second
    assert first.content_hash == second.content_hash
    train_families = {item.source_family for item in first.train}
    evaluation_families = {item.source_family for item in first.evaluation}
    assert train_families.isdisjoint(evaluation_families)
    family_a_splits = {
        split
        for split, items in (("train", first.train), ("evaluation", first.evaluation))
        if sum(item.source_family.endswith(":conversation-a") for item in items) == 2
    }
    assert len(family_a_splits) == 1


def test_changed_case_version_changes_manifest_without_removing_history() -> None:
    original = _case(trace_id="conversation-a", version=1)
    updated = original.model_copy(update={"case_version": 2})

    first = build_dataset_manifest(
        [original], dataset_id="support_v1", dataset_version=1, split_seed="seed"
    )
    second = build_dataset_manifest(
        [original, updated], dataset_id="support_v2", dataset_version=2, split_seed="seed"
    )

    assert first.content_hash != second.content_hash
    assert {(item.case_id, item.case_version) for item in (*second.train, *second.evaluation)} == {
        (str(original.case_id), 1),
        (str(original.case_id), 2),
    }
