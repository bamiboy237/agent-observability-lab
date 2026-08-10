"""This module defines the evidence-linked baseline/candidate comparison.

A comparison runs the same bundle and starting state with the baseline and
the candidate configuration, then returns one of four verdicts:
``candidate_passes``, ``candidate_regresses``, ``no_material_difference``, or
``insufficient_evidence``. Every result links through the bundle to the
source evidence. Any safety regression or missing required measurement
blocks ``candidate_passes``.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.bundle.schemas import SimulationBundle
from app.domain.comparison.evaluators import (
    SAFETY_EVALUATORS,
    EvaluatorReport,
)
from app.domain.evidence.schemas import TraceSourceRef
from app.domain.simulation.adapters import StateMutation
from app.domain.simulation.runner import RunVerdict, SimulationRun

COMPARISON_SCHEMA_VERSION = "1.0.0"


class ComparisonVerdict(StrEnum):
    """This enum defines the four comparison outcomes."""

    CANDIDATE_PASSES = "candidate_passes"
    CANDIDATE_REGRESSES = "candidate_regresses"
    NO_MATERIAL_DIFFERENCE = "no_material_difference"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class CriterionDelta(BaseModel):
    """This class stores one measured difference between two runs."""

    model_config = ConfigDict(extra="forbid")

    criterion: str = Field(min_length=1, max_length=200)
    baseline: str = Field(min_length=1, max_length=1000)
    candidate: str = Field(min_length=1, max_length=1000)
    changed: bool
    regression: bool


class RunComparison(BaseModel):
    """This class stores the evidence-linked result of one comparison.

    The result carries both normalized runs, the per-criterion deltas, the
    blocked reasons, and the bundle and evidence links. The verdict is
    deterministic: it derives only from the two runs and the bundle.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=COMPARISON_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    bundle_id: UUID
    bundle_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_id: str
    evidence_ref: TraceSourceRef | None = None
    evidence_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    baseline_run: SimulationRun
    candidate_run: SimulationRun
    verdict: ComparisonVerdict
    deltas: tuple[CriterionDelta, ...] = ()
    regressions: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()


def _comparable(run: SimulationRun) -> bool:
    return run.verdict in (RunVerdict.REPRODUCED, RunVerdict.ACCEPTED, RunVerdict.FAILED)


def _evaluator_map(report: EvaluatorReport) -> dict[str, bool]:
    return {result.evaluator: result.passed for result in report.results}


def _mutation_key(mutation: StateMutation) -> tuple[str, str, str, object, object, str]:
    return (
        mutation.resource,
        mutation.resource_id,
        mutation.field,
        mutation.before,
        mutation.after,
        mutation.reason_code,
    )


def _measured(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "none"
    return f"{value:.{digits}f}"


def _token_measurement(run: SimulationRun) -> int | None:
    """Return measured token usage, keeping an unreported default distinct."""
    return run.total_tokens if run.total_tokens > 0 else None


def _validate_run_identity(
    run: SimulationRun,
    bundle: SimulationBundle,
    *,
    side: str,
) -> None:
    mismatches: list[str] = []
    if run.bundle_id != bundle.bundle_id:
        mismatches.append("bundle_id")
    if run.bundle_content_hash != bundle.content_hash:
        mismatches.append("bundle_content_hash")
    if run.scenario_id != bundle.scenario.scenario_id:
        mismatches.append("scenario_id")
    if mismatches:
        raise ValueError(
            f"{side} run does not belong to the supplied bundle: "
            f"mismatched {', '.join(mismatches)}"
        )


def _deltas(
    baseline: SimulationRun,
    candidate: SimulationRun,
    bundle: SimulationBundle,
) -> tuple[CriterionDelta, ...]:
    deltas: list[CriterionDelta] = []

    def _behavior(run: SimulationRun) -> str:
        response = run.response
        if response is None:
            return f"{run.verdict.value}:no-response"
        return f"{run.verdict.value}:{response.outcome.value}:{response.reason_code.value}"

    expected_outcome = bundle.expected_behavior.outcome
    baseline_matches = (
        baseline.response is not None and baseline.response.outcome is expected_outcome
    )
    candidate_matches = (
        candidate.response is not None and candidate.response.outcome is expected_outcome
    )
    outcome_regression = baseline_matches and not candidate_matches

    baseline_behavior = _behavior(baseline)
    candidate_behavior = _behavior(candidate)
    deltas.append(
        CriterionDelta(
            criterion="outcome",
            baseline=baseline_behavior,
            candidate=candidate_behavior,
            changed=baseline_behavior != candidate_behavior,
            regression=outcome_regression,
        )
    )
    baseline_evaluators = _evaluator_map(baseline.evaluators)
    candidate_evaluators = _evaluator_map(candidate.evaluators)
    for evaluator in sorted(set(baseline_evaluators) | set(candidate_evaluators)):
        baseline_passed = baseline_evaluators.get(evaluator, False)
        candidate_passed = candidate_evaluators.get(evaluator, False)
        deltas.append(
            CriterionDelta(
                criterion=f"evaluator:{evaluator}",
                baseline="pass" if baseline_passed else "fail",
                candidate="pass" if candidate_passed else "fail",
                changed=baseline_passed != candidate_passed,
                regression=baseline_passed and not candidate_passed,
            )
        )
    baseline_mutations = tuple(_mutation_key(m) for m in baseline.mutations)
    candidate_mutations = tuple(_mutation_key(m) for m in candidate.mutations)
    deltas.append(
        CriterionDelta(
            criterion="state",
            baseline="; ".join(f"{key[0]}:{key[1]}:{key[5]}" for key in baseline_mutations)
            or "none",
            candidate="; ".join(f"{key[0]}:{key[1]}:{key[5]}" for key in candidate_mutations)
            or "none",
            changed=baseline_mutations != candidate_mutations,
            regression=False,
        )
    )
    deltas.append(
        CriterionDelta(
            criterion="trajectory",
            baseline=",".join(baseline.tool_calls) or "none",
            candidate=",".join(candidate.tool_calls) or "none",
            changed=baseline.tool_calls != candidate.tool_calls,
            regression=False,
        )
    )
    deltas.append(
        CriterionDelta(
            criterion="retries",
            baseline=str(baseline.retries),
            candidate=str(candidate.retries),
            changed=baseline.retries != candidate.retries,
            regression=candidate.retries > baseline.retries,
        )
    )
    deltas.append(
        CriterionDelta(
            criterion="latency_ms",
            baseline=_measured(baseline.total_latency_ms),
            candidate=_measured(candidate.total_latency_ms),
            changed=baseline.total_latency_ms != candidate.total_latency_ms,
            regression=False,
        )
    )
    baseline_tokens = _token_measurement(baseline)
    candidate_tokens = _token_measurement(candidate)
    deltas.append(
        CriterionDelta(
            criterion="tokens",
            baseline=str(baseline_tokens) if baseline_tokens is not None else "none",
            candidate=str(candidate_tokens) if candidate_tokens is not None else "none",
            changed=baseline_tokens != candidate_tokens,
            regression=False,
        )
    )
    deltas.append(
        CriterionDelta(
            criterion="cost_usd",
            baseline=_measured(baseline.cost_usd, digits=6),
            candidate=_measured(candidate.cost_usd, digits=6),
            changed=baseline.cost_usd != candidate.cost_usd,
            regression=False,
        )
    )
    return tuple(deltas)


def _missing_measurements(
    bundle: SimulationBundle, baseline: SimulationRun, candidate: SimulationRun
) -> tuple[str, ...]:
    budgets = bundle.expected_behavior.budgets
    missing: list[str] = []
    if budgets.performance_budget_ms is not None:
        if baseline.total_latency_ms is None or candidate.total_latency_ms is None:
            missing.append("total latency")
    if budgets.max_cost_usd is not None:
        if baseline.cost_usd is None or candidate.cost_usd is None:
            missing.append("estimated cost")
    if budgets.max_tokens is not None:
        if _token_measurement(baseline) is None or _token_measurement(candidate) is None:
            missing.append("token usage")
    return tuple(missing)


def compare_runs(
    baseline: SimulationRun,
    candidate: SimulationRun,
    bundle: SimulationBundle,
) -> RunComparison:
    """This function compares two runs of the same bundle deterministically.

    The verdict rules are: both runs must be comparable and every declared
    measurement must be present; any safety evaluator regression or outcome
    regression blocks the candidate; increased retries count as a regression;
    the candidate passes only when it improves the outcome match, fixes a
    failed evaluator, or removes retries; otherwise the runs show no material
    difference. Latency, token, and cost deltas are always visible but only
    change the verdict through declared budgets, and a different tool path is
    recorded without counting as an improvement by itself.
    """
    if bundle.bundle_id is None or bundle.content_hash is None:
        raise ValueError("bundle has no derived identifier or content hash")
    _validate_run_identity(baseline, bundle, side="baseline")
    _validate_run_identity(candidate, bundle, side="candidate")
    deltas = _deltas(baseline, candidate, bundle)
    blocked: list[str] = []
    regressions: list[str] = []

    if not _comparable(baseline) or not _comparable(candidate):
        verdict = ComparisonVerdict.INSUFFICIENT_EVIDENCE
        blocked.append(
            f"baseline verdict {baseline.verdict.value!r} or candidate verdict "
            f"{candidate.verdict.value!r} is not a completed comparable run"
        )
        return RunComparison(
            bundle_id=bundle.bundle_id,
            bundle_content_hash=bundle.content_hash or "",
            scenario_id=bundle.scenario.scenario_id,
            evidence_ref=bundle.evidence_ref,
            evidence_content_hash=bundle.evidence_content_hash,
            baseline_run=baseline,
            candidate_run=candidate,
            verdict=verdict,
            deltas=deltas,
            regressions=(),
            blocked_reasons=tuple(blocked),
        )

    missing = _missing_measurements(bundle, baseline, candidate)
    for measurement in missing:
        blocked.append(f"missing required measurement: {measurement}")

    for delta in deltas:
        criterion = delta.criterion
        if delta.regression:
            regressions.append(criterion)
            if criterion.startswith("evaluator:"):
                evaluator = criterion.split(":", 1)[1]
                if evaluator in SAFETY_EVALUATORS:
                    blocked.append(f"safety regression on evaluator {evaluator!r}")
            elif criterion == "outcome":
                blocked.append("business outcome regression")

    if blocked:
        verdict = (
            ComparisonVerdict.INSUFFICIENT_EVIDENCE
            if any("missing required measurement" in reason for reason in blocked)
            else ComparisonVerdict.CANDIDATE_REGRESSES
        )
    elif regressions:
        verdict = ComparisonVerdict.CANDIDATE_REGRESSES
    else:
        # A candidate passes only when it improves an outcome match, fixes a
        # failed evaluator, or removes retries. Latency, token, cost, and
        # trajectory differences are recorded in the deltas but never count
        # as an improvement by themselves: budgets remain the deterministic
        # gate for latency and cost, and a different tool path is not
        # automatically better.
        improvements: list[str] = []
        expected_outcome = bundle.expected_behavior.outcome
        baseline_matches = (
            baseline.response is not None and baseline.response.outcome is expected_outcome
        )
        candidate_matches = (
            candidate.response is not None and candidate.response.outcome is expected_outcome
        )
        if not baseline_matches and candidate_matches:
            improvements.append("outcome")
        for delta in deltas:
            if (
                delta.criterion.startswith("evaluator:")
                and delta.baseline == "fail"
                and delta.candidate == "pass"
            ):
                improvements.append(delta.criterion)
        if candidate.retries < baseline.retries:
            improvements.append("retries")
        verdict = (
            ComparisonVerdict.CANDIDATE_PASSES
            if improvements
            else ComparisonVerdict.NO_MATERIAL_DIFFERENCE
        )

    return RunComparison(
        bundle_id=bundle.bundle_id,
        bundle_content_hash=bundle.content_hash or "",
        scenario_id=bundle.scenario.scenario_id,
        evidence_ref=bundle.evidence_ref,
        evidence_content_hash=bundle.evidence_content_hash,
        baseline_run=baseline,
        candidate_run=candidate,
        verdict=verdict,
        deltas=deltas,
        regressions=tuple(regressions),
        blocked_reasons=tuple(blocked),
    )
