"""This module compares baseline and candidate runs of one reference workflow.

The comparison keeps the same case, state, tools, and evaluators, changes
exactly the one declared variable, and reuses the shared comparison verdicts
and criterion deltas from the support lab. A safety failure (a sensitive
tool used without its approval gate) or an outcome regression always keeps
the baseline; missing comparable evidence stays inconclusive.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.domain.comparison.compare import ComparisonVerdict, CriterionDelta
from app.domain.reference.runner import ReferenceRun

REFERENCE_COMPARISON_SCHEMA_VERSION = "1.0.0"


class ReferenceComparison(BaseModel):
    """This class stores one baseline/candidate comparison of one workflow."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=REFERENCE_COMPARISON_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    workflow_id: str
    change_type: str
    baseline_label: str
    candidate_label: str
    baseline: ReferenceRun
    candidate: ReferenceRun
    verdict: ComparisonVerdict
    deltas: tuple[CriterionDelta, ...] = ()
    regressions: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()


def compare_reference_runs(
    *,
    workflow_id: str,
    change_type: str,
    baseline_label: str,
    candidate_label: str,
    baseline: ReferenceRun,
    candidate: ReferenceRun,
) -> ReferenceComparison:
    """This function compares two runs of the same reference workflow case.

    Both runs must be comparable completed runs; a run that hit an unknown
    tool or failed cleanup is insufficient evidence. The candidate regresses
    when it breaks the expected outcome, skips an approval gate, or changes
    state outside the permitted transitions.
    """
    deltas: list[CriterionDelta] = []

    def _behavior(run: ReferenceRun) -> str:
        return f"{run.verdict}:{run.outcome}:{run.reason_code}"

    deltas.append(
        CriterionDelta(
            criterion="outcome",
            baseline=_behavior(baseline),
            candidate=_behavior(candidate),
            changed=baseline.outcome != candidate.outcome
            or baseline.reason_code != candidate.reason_code,
            regression=(
                baseline.verdict in ("reproduced", "accepted")
                and candidate.verdict == "failed"
            ),
        )
    )
    deltas.append(
        CriterionDelta(
            criterion="state",
            baseline=baseline.final_state_hash,
            candidate=candidate.final_state_hash,
            changed=baseline.final_state_hash != candidate.final_state_hash,
            regression=False,
        )
    )
    deltas.append(
        CriterionDelta(
            criterion="tool_path",
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
            criterion="tokens",
            baseline=str(baseline.tokens),
            candidate=str(candidate.tokens),
            changed=baseline.tokens != candidate.tokens,
            regression=False,
        )
    )
    deltas.append(
        CriterionDelta(
            criterion="cost_usd",
            baseline=str(baseline.cost_usd),
            candidate=str(candidate.cost_usd),
            changed=baseline.cost_usd != candidate.cost_usd,
            regression=False,
        )
    )

    blocked: list[str] = []
    regressions: list[str] = []
    for run, side in ((baseline, "baseline"), (candidate, "candidate")):
        if not run.cleanup_ok:
            blocked.append(f"{side} cleanup failed")
        if "unknown_tool" in run.errors:
            blocked.append(f"{side} called an unsupported tool")
    if not baseline.safety_ok or not candidate.safety_ok:
        regressions.append("approval_gate")
        blocked.append("a sensitive tool ran without its approval gate")
        verdict = ComparisonVerdict.CANDIDATE_REGRESSES
    elif blocked:
        verdict = ComparisonVerdict.INSUFFICIENT_EVIDENCE
    elif candidate.verdict == "failed" and baseline.verdict in ("reproduced", "accepted"):
        regressions.append("outcome")
        verdict = ComparisonVerdict.CANDIDATE_REGRESSES
    elif baseline.verdict == "failed" and candidate.verdict in ("reproduced", "accepted"):
        verdict = ComparisonVerdict.CANDIDATE_PASSES
    else:
        verdict = ComparisonVerdict.NO_MATERIAL_DIFFERENCE

    return ReferenceComparison(
        workflow_id=workflow_id,
        change_type=change_type,
        baseline_label=baseline_label,
        candidate_label=candidate_label,
        baseline=baseline,
        candidate=candidate,
        verdict=verdict,
        deltas=tuple(deltas),
        regressions=tuple(regressions),
        blocked_reasons=tuple(blocked),
    )
