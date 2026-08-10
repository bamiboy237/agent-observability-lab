"""This module implements the Model Lab cohort comparison.

The Model Lab holds prompt, retrieval, tools, workflow, routing, policy,
evaluators, fixtures, and starting state constant because every candidate run
reuses the same bundle, and changes only the hosted model. It compares task
success, case regressions, latency, tokens, estimated cost, cost per
successful task, retries, tool use, and policy outcomes, shows case-level
trade-offs and cohort totals, and refuses a recommendation when too few
comparable completed cases exist.
"""

from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.adapters.pydantic_ai_agent import ModelConfig
from app.domain.agent.schemas import ReasonCode
from app.domain.bundle.schemas import SimulationBundle
from app.domain.comparison.evaluators import ALL_EVALUATORS, SAFETY_EVALUATORS, Evaluator
from app.domain.simulation.provisioner import ProvisionerFactory
from app.domain.simulation.runner import RunVerdict, SimulationRun, run_bundle

MODEL_LAB_SCHEMA_VERSION = "1.0.0"
MIN_COMPARABLE_CASES = 3
MAX_COHORT_BUNDLES = 20


class ModelLabVerdict(StrEnum):
    """This enum defines the cohort-level recommendation."""

    RECOMMEND_CANDIDATE = "recommend_candidate"
    KEEP_BASELINE = "keep_baseline"
    INCONCLUSIVE = "inconclusive"


class ModelCaseOutcome(BaseModel):
    """This class stores one model's outcome for one bundle."""

    model_config = ConfigDict(extra="forbid")

    verdict: RunVerdict
    task_success: bool
    total_latency_ms: float | None = None
    tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = None
    retries: int = 0
    tool_calls: tuple[str, ...] = ()
    policy_outcome: str | None = None


class ModelCaseResult(BaseModel):
    """This class stores the baseline and candidate outcomes of one bundle."""

    model_config = ConfigDict(extra="forbid")

    bundle_id: UUID
    scenario_id: str
    comparable: bool
    regression: bool
    baseline: ModelCaseOutcome
    candidate: ModelCaseOutcome
    non_comparable_reason: str | None = None


class ModelSideTotals(BaseModel):
    """This class stores one model's cohort totals."""

    model_config = ConfigDict(extra="forbid")

    success_count: int = 0
    success_rate: float = 0.0
    total_cost: float = 0.0
    cost_per_successful_task: float | None = None
    total_latency_ms: float = 0.0
    average_latency_ms: float = 0.0
    total_tokens: int = 0
    latency_measurements: int = 0
    token_measurements: int = 0
    cost_measurements: int = 0
    total_retries: int = 0
    tool_use: dict[str, int] = Field(default_factory=dict)
    policy_outcomes: dict[str, int] = Field(default_factory=dict)


class ModelLabTotals(BaseModel):
    """This class stores the cohort totals for both models."""

    model_config = ConfigDict(extra="forbid")

    comparable_cases: int = 0
    regressions: int = 0
    safety_regressions: int = 0
    unexpected_state_changes: int = 0
    baseline: ModelSideTotals = Field(default_factory=ModelSideTotals)
    candidate: ModelSideTotals = Field(default_factory=ModelSideTotals)


class ModelLabResult(BaseModel):
    """This class stores the bounded cohort comparison and its recommendation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=MODEL_LAB_SCHEMA_VERSION,
        pattern=r"^\d+\.\d+\.\d+$",
    )
    cohort: tuple[ModelCaseResult, ...] = ()
    totals: ModelLabTotals = Field(default_factory=ModelLabTotals)
    verdict: ModelLabVerdict = ModelLabVerdict.INCONCLUSIVE
    verdict_reason: str = Field(min_length=1, max_length=1000)


def _policy_outcome(reason_code: ReasonCode) -> str | None:
    if reason_code is ReasonCode.POLICY_ANSWER:
        return "grounded"
    if reason_code is ReasonCode.POLICY_ANSWER_UNGROUNDED:
        return "ungrounded"
    return None


def _required_evaluators_pass(run: SimulationRun) -> bool:
    """This function reports whether every required safety and state evaluator passed.

    A missing required result counts as a failure: an aborted or partial run
    must never look successful by omission.
    """
    present = {result.evaluator: result.passed for result in run.evaluators.results}
    return all(name in present and present[name] for name in SAFETY_EVALUATORS)


def _task_success(run: SimulationRun, bundle: SimulationBundle) -> bool:
    """This function decides whether one run completed the task successfully.

    A case counts as successful only when the run produced the expected
    business outcome AND every required safety and state evaluator passed.
    A matching outcome alone is never enough, and neither is a clean
    evaluator report without the expected outcome.
    """
    if run.response is None or run.response.outcome is not bundle.expected_behavior.outcome:
        return False
    return _required_evaluators_pass(run)


def _safety_failure(run: SimulationRun) -> bool:
    """This function reports whether any required safety or state evaluator failed."""
    return any(
        result.evaluator in SAFETY_EVALUATORS and not result.passed
        for result in run.evaluators.results
    )


def _evaluator_failed(run: SimulationRun, evaluator: str) -> bool:
    """This function reports whether one named evaluator failed the run."""
    return any(
        result.evaluator == evaluator and not result.passed for result in run.evaluators.results
    )


def _side_totals(outcomes: Sequence[ModelCaseOutcome]) -> ModelSideTotals:
    successes = sum(1 for outcome in outcomes if outcome.task_success)
    latency_measurements = sum(
        1 for outcome in outcomes if outcome.total_latency_ms is not None
    )
    token_measurements = sum(1 for outcome in outcomes if outcome.tokens is not None)
    cost_measurements = sum(1 for outcome in outcomes if outcome.cost_usd is not None)
    total_cost = sum(outcome.cost_usd or 0.0 for outcome in outcomes)
    total_latency = sum(outcome.total_latency_ms or 0.0 for outcome in outcomes)
    total_tokens = sum(outcome.tokens or 0 for outcome in outcomes)
    total_retries = sum(outcome.retries for outcome in outcomes)
    tool_use: dict[str, int] = {}
    for outcome in outcomes:
        for tool in outcome.tool_calls:
            tool_use[tool] = tool_use.get(tool, 0) + 1
    policy_outcomes: dict[str, int] = {}
    for outcome in outcomes:
        if outcome.policy_outcome is not None:
            policy_outcomes[outcome.policy_outcome] = (
                policy_outcomes.get(outcome.policy_outcome, 0) + 1
            )
    return ModelSideTotals(
        success_count=successes,
        success_rate=round(successes / len(outcomes), 4) if outcomes else 0.0,
        total_cost=round(total_cost, 6),
        cost_per_successful_task=(round(total_cost / successes, 6) if successes else None),
        total_latency_ms=round(total_latency, 2),
        average_latency_ms=(
            round(total_latency / latency_measurements, 2) if latency_measurements else 0.0
        ),
        total_tokens=total_tokens,
        latency_measurements=latency_measurements,
        token_measurements=token_measurements,
        cost_measurements=cost_measurements,
        total_retries=total_retries,
        tool_use=dict(sorted(tool_use.items())),
        policy_outcomes=dict(sorted(policy_outcomes.items())),
    )


def _recommendation(
    totals: ModelLabTotals,
    min_comparable_cases: int,
) -> tuple[ModelLabVerdict, str]:
    comparable = totals.comparable_cases
    if comparable < min_comparable_cases:
        return (
            ModelLabVerdict.INCONCLUSIVE,
            (
                f"too few comparable completed cases: {comparable} of at least "
                f"{min_comparable_cases} required; run more accepted bundles "
                "before recommending a model"
            ),
        )
    if totals.regressions > 0:
        return (
            ModelLabVerdict.KEEP_BASELINE,
            (
                f"candidate regressed task success on {totals.regressions} "
                "comparable case(s); the baseline stays"
            ),
        )
    if totals.safety_regressions > 0:
        return (
            ModelLabVerdict.KEEP_BASELINE,
            (
                f"candidate regressed a required safety or state evaluator on "
                f"{totals.safety_regressions} comparable case(s); a candidate "
                "with a safety regression is never recommended"
            ),
        )
    if totals.unexpected_state_changes > 0:
        return (
            ModelLabVerdict.KEEP_BASELINE,
            (
                f"candidate changed state outside the scenario's permitted "
                f"transitions on {totals.unexpected_state_changes} comparable "
                "case(s); a candidate with unexpected state changes is never "
                "recommended"
            ),
        )
    baseline = totals.baseline
    candidate = totals.candidate
    if baseline.success_count == 0 and candidate.success_count == 0:
        return (
            ModelLabVerdict.INCONCLUSIVE,
            "neither model completed a successful task; there is no successful behavior to compare",
        )
    missing: list[str] = []
    for name, measured in (
        ("baseline latency", baseline.latency_measurements),
        ("candidate latency", candidate.latency_measurements),
        ("baseline tokens", baseline.token_measurements),
        ("candidate tokens", candidate.token_measurements),
        ("baseline cost", baseline.cost_measurements),
        ("candidate cost", candidate.cost_measurements),
    ):
        if measured < comparable:
            missing.append(name)
    if missing:
        return (
            ModelLabVerdict.INCONCLUSIVE,
            f"missing measurements for {', '.join(missing)}; no model recommendation",
        )
    if candidate.success_rate < baseline.success_rate:
        return (
            ModelLabVerdict.KEEP_BASELINE,
            (
                f"candidate task success {candidate.success_rate} is below the "
                f"baseline {baseline.success_rate}; the baseline stays"
            ),
        )
    baseline_cost = baseline.cost_per_successful_task
    candidate_cost = candidate.cost_per_successful_task
    if baseline_cost is not None and candidate_cost is not None and candidate_cost > baseline_cost:
        return (
            ModelLabVerdict.KEEP_BASELINE,
            (
                f"candidate costs ${candidate_cost:.4f} per successful task versus "
                f"${baseline_cost:.4f} for the baseline without a success gain; "
                "the baseline stays"
            ),
        )
    if (
        candidate.success_rate == baseline.success_rate
        and baseline_cost is not None
        and candidate_cost is not None
        and candidate_cost == baseline_cost
    ):
        return (
            ModelLabVerdict.INCONCLUSIVE,
            (
                "the models are equivalent on task success and cost per "
                "successful task; no recommendation"
            ),
        )
    if candidate.success_rate >= baseline.success_rate and (
        candidate_cost is None or baseline_cost is None or candidate_cost <= baseline_cost
    ):
        return (
            ModelLabVerdict.RECOMMEND_CANDIDATE,
            (
                f"candidate matches or improves task success "
                f"({candidate.success_rate} vs {baseline.success_rate}) at equal "
                "or lower cost per successful task"
            ),
        )
    return ModelLabVerdict.INCONCLUSIVE, "the cohort evidence is not decisive"


async def run_model_lab(
    *,
    bundles: Sequence[SimulationBundle],
    baseline_model_config: ModelConfig,
    candidate_model_config: ModelConfig,
    provisioner_factory: ProvisionerFactory,
    min_comparable_cases: int = MIN_COMPARABLE_CASES,
    max_bundles: int = MAX_COHORT_BUNDLES,
    evaluators: Sequence[Evaluator] = ALL_EVALUATORS,
) -> ModelLabResult:
    """This function compares two hosted models on one explicitly bounded cohort.

    Every bundle runs twice: once with the baseline model and once with the
    candidate model, through the same provisioner factory, so the starting
    state, prompt, tools, fixtures, and evaluators stay constant.
    """
    if not bundles:
        return ModelLabResult(
            verdict=ModelLabVerdict.INCONCLUSIVE,
            verdict_reason="the cohort is empty",
        )
    if len(bundles) > max_bundles:
        raise ValueError(
            f"the cohort is explicitly bounded: {len(bundles)} bundles exceed the "
            f"{max_bundles} limit"
        )

    cases: list[ModelCaseResult] = []
    baseline_outcomes: list[ModelCaseOutcome] = []
    candidate_outcomes: list[ModelCaseOutcome] = []
    regressions = 0
    safety_regressions = 0
    unexpected_state_changes = 0

    for bundle in bundles:
        baseline_run = await run_bundle(
            bundle=bundle,
            provisioner_factory=provisioner_factory,
            model_config=baseline_model_config,
            evaluators=evaluators,
        )
        candidate_run = await run_bundle(
            bundle=bundle,
            provisioner_factory=provisioner_factory,
            model_config=candidate_model_config,
            evaluators=evaluators,
        )
        baseline_success = _task_success(baseline_run, bundle)
        candidate_success = _task_success(candidate_run, bundle)
        baseline_aborted = baseline_run.verdict in (
            RunVerdict.UNEXPECTED_ACCESS,
            RunVerdict.MISSING_COVERAGE,
        )
        candidate_aborted = candidate_run.verdict in (
            RunVerdict.UNEXPECTED_ACCESS,
            RunVerdict.MISSING_COVERAGE,
        )
        comparable = (
            not baseline_aborted
            and not candidate_aborted
            and baseline_run.response is not None
            and candidate_run.response is not None
        )
        non_comparable_reason: str | None = None
        if not comparable:
            reasons: list[str] = []
            if baseline_run.response is None or baseline_aborted:
                reasons.append(
                    f"baseline returned {baseline_run.verdict.value} without a typed response"
                )
            if candidate_run.response is None or candidate_aborted:
                reasons.append(
                    f"candidate returned {candidate_run.verdict.value} without a typed response"
                )
            non_comparable_reason = "; ".join(reasons)
        regression = comparable and baseline_success and not candidate_success
        if regression:
            regressions += 1
        baseline_safety_ok = not _safety_failure(baseline_run)
        candidate_safety_ok = not _safety_failure(candidate_run)
        if comparable and baseline_safety_ok and not candidate_safety_ok:
            safety_regressions += 1
        if comparable and _evaluator_failed(candidate_run, "unexpected_state_changes"):
            unexpected_state_changes += 1

        def _outcome(run: SimulationRun, success: bool) -> ModelCaseOutcome:
            response = run.response
            return ModelCaseOutcome(
                verdict=run.verdict,
                task_success=success,
                total_latency_ms=run.total_latency_ms,
                tokens=run.total_tokens if run.total_tokens > 0 else None,
                cost_usd=run.cost_usd,
                retries=run.retries,
                tool_calls=run.tool_calls,
                policy_outcome=(
                    _policy_outcome(response.reason_code) if response is not None else None
                ),
            )

        baseline_outcome = _outcome(baseline_run, baseline_success)
        candidate_outcome = _outcome(candidate_run, candidate_success)
        cases.append(
            ModelCaseResult(
                bundle_id=bundle.bundle_id or UUID(int=0),
                scenario_id=bundle.scenario.scenario_id,
                comparable=comparable,
                regression=regression,
                baseline=baseline_outcome,
                candidate=candidate_outcome,
                non_comparable_reason=non_comparable_reason,
            )
        )
        if comparable:
            baseline_outcomes.append(baseline_outcome)
            candidate_outcomes.append(candidate_outcome)

    totals = ModelLabTotals(
        comparable_cases=len(baseline_outcomes),
        regressions=regressions,
        safety_regressions=safety_regressions,
        unexpected_state_changes=unexpected_state_changes,
        baseline=_side_totals(baseline_outcomes),
        candidate=_side_totals(candidate_outcomes),
    )
    verdict, reason = _recommendation(totals, min_comparable_cases)
    return ModelLabResult(
        cohort=tuple(cases),
        totals=totals,
        verdict=verdict,
        verdict_reason=reason,
    )
