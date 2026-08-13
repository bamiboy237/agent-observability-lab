"""Explainable failure feature extraction from canonical trace evidence."""

from collections.abc import Iterable
from uuid import UUID, uuid5

from app.domain.evidence.schemas import TraceEventKind, TraceEvidence, TraceOutcome
from app.domain.failures.schemas import FailureCandidate, FailureKind, FeedbackAnnotation

FEATURE_NAMESPACE = UUID("f58b8d61-8c80-46d7-9db7-8f5d10d3ed35")
ACCEPTED_SUCCESS_REASONS = frozenset({"ok", "order_status_ok", "policy_answer"})


def _event_values(evidence: TraceEvidence, key: str) -> list[object]:
    return [event.attributes[key] for event in evidence.events if key in event.attributes]


def _accepted_success(evidence: TraceEvidence) -> bool:
    """Return true only for a completed trace with no failure signal."""
    if evidence.outcome is not TraceOutcome.COMPLETED:
        return False
    if evidence.reason_code not in ACCEPTED_SUCCESS_REASONS:
        return False
    if (
        evidence.retry_count
        or evidence.confirmation
        and evidence.confirmation.required
        and not evidence.confirmation.verified
    ):
        return False
    if any(event.error_code for event in evidence.events):
        return False
    if any(call.error_code for call in evidence.dependency_calls):
        return False
    if evidence.timing.budget_ms and evidence.timing.total_latency_ms:
        if evidence.timing.total_latency_ms > evidence.timing.budget_ms:
            return False
    grounded = _event_values(evidence, "support.policy.grounded")
    return not grounded or all(value is True for value in grounded)


def _kind_and_events(evidence: TraceEvidence) -> tuple[FailureKind, tuple[str, ...]]:
    """Classify one trace using ordered, hand-named rules."""
    events = evidence.events
    routing = [event for event in events if event.kind is TraceEventKind.ROUTING]
    retrieval = [event for event in events if event.kind is TraceEventKind.RETRIEVAL]
    tools = [event for event in events if event.kind is TraceEventKind.TOOL]
    generation = [
        event for event in events if event.kind in (TraceEventKind.ANSWER, TraceEventKind.MODEL)
    ]
    policy = [event for event in events if event.kind is TraceEventKind.POLICY]
    infrastructure = [
        event
        for event in events
        if event.kind is TraceEventKind.DATABASE
        and event.error_code in {"timeout", "unavailable", "connection_error"}
    ]
    if routing and (
        evidence.reason_code.startswith("routing") or any(event.error_code for event in routing)
    ):
        return FailureKind.ROUTING, tuple(event.event_id for event in routing)
    if retrieval and (
        evidence.reason_code.startswith("retrieval")
        or any(event.error_code for event in retrieval)
        or any(value is False for value in _event_values(evidence, "support.policy.grounded"))
    ):
        return FailureKind.RETRIEVAL, tuple(event.event_id for event in retrieval)
    if (
        policy
        or evidence.confirmation is not None
        or any(value is False for value in _event_values(evidence, "support.policy.grounded"))
        or evidence.reason_code.startswith("policy")
        or evidence.reason_code.startswith("refund_blocked")
    ):
        selected = policy or [
            event for event in events if event.kind is TraceEventKind.CONFIRMATION
        ]
        return FailureKind.POLICY, tuple(event.event_id for event in selected)
    if (
        infrastructure
        or (
            evidence.retry_count
            and any(
                call.kind is TraceEventKind.DATABASE
                and call.error_code in {"timeout", "unavailable"}
                for call in evidence.dependency_calls
            )
        )
        or any(
            call.kind is TraceEventKind.DATABASE
            and call.error_code in {"timeout", "unavailable", "connection_error"}
            for call in evidence.dependency_calls
        )
        or evidence.reason_code.startswith(("timeout", "infrastructure", "db_"))
        or (
            evidence.timing.budget_ms is not None
            and evidence.timing.total_latency_ms is not None
            and evidence.timing.total_latency_ms > evidence.timing.budget_ms
        )
    ):
        selected = infrastructure or [
            event
            for event in events
            if event.kind is TraceEventKind.RETRY or event.error_code is not None
        ]
        return FailureKind.INFRASTRUCTURE, tuple(event.event_id for event in selected)
    if generation and (
        evidence.reason_code.startswith("generation")
        or any(event.error_code for event in generation)
    ):
        return FailureKind.GENERATION, tuple(event.event_id for event in generation)
    if tools and any(event.error_code for event in tools):
        return FailureKind.TOOL, tuple(event.event_id for event in tools)
    # A non-success outcome without a specialized marker is a generation error.
    return FailureKind.GENERATION, (events[-1].event_id,)


def extract_failure_candidate(
    evidence: TraceEvidence,
    feedback: Iterable[FeedbackAnnotation] = (),
    *,
    dataset_version: int | None = None,
) -> FailureCandidate | None:
    """Return one candidate with every feature traceable to source evidence.

    Accepted success traces return ``None``.  This is intentionally a rules
    baseline, not a text classifier.
    """
    if _accepted_success(evidence):
        return None
    predicted_kind, kind_event_ids = _kind_and_events(evidence)
    event_ids = set(kind_event_ids)
    features: dict[str, bool | int | float | str] = {
        "retry_count": evidence.retry_count,
        "escalated": any(event.kind is TraceEventKind.ESCALATION for event in evidence.events),
    }
    retrieval_scores = [
        float(value)
        for value in _event_values(evidence, "retrieval.score")
        if isinstance(value, (int, float))
    ]
    if retrieval_scores:
        features["min_retrieval_score"] = min(retrieval_scores)
    tool_errors = [
        event.error_code or str(event.attributes.get("tool.error.code"))
        for event in evidence.events
        if event.kind is TraceEventKind.TOOL
        and (event.error_code or event.attributes.get("tool.error.code"))
    ]
    if tool_errors:
        features["tool_error_code"] = tool_errors[0]
    db_errors = [
        event.error_code or str(event.attributes.get("db.error.code"))
        for event in evidence.events
        if event.kind is TraceEventKind.DATABASE
        and (event.error_code or event.attributes.get("db.error.code"))
    ]
    if db_errors:
        features["db_error_code"] = db_errors[0]
    grounded = _event_values(evidence, "support.policy.grounded")
    if grounded:
        features["policy_grounded"] = all(value is True for value in grounded)
    if evidence.timing.budget_ms is not None and evidence.timing.total_latency_ms is not None:
        features["latency_over_budget"] = (
            evidence.timing.total_latency_ms > evidence.timing.budget_ms
        )
    if evidence.reason_code:
        features["reason_code"] = evidence.reason_code
    feedback_list = tuple(feedback)
    if feedback_list:
        features["feedback_label"] = feedback_list[-1].label
        event_ids.update(item.event_id for item in feedback_list if item.event_id is not None)
    event_ids.update(
        event.event_id
        for event in evidence.events
        if event.error_code is not None
        or event.kind in (TraceEventKind.RETRY, TraceEventKind.ESCALATION)
        or any(
            key in event.attributes
            for key in (
                "support.policy.grounded",
                "retrieval.score",
                "db.latency.ms",
                "tool.error.code",
            )
        )
    )
    ordered_event_ids = tuple(sorted(event_ids))
    if not ordered_event_ids:
        ordered_event_ids = (evidence.events[0].event_id,)
    candidate_id = uuid5(FEATURE_NAMESPACE, f"{evidence.evidence_id}|{predicted_kind.value}")
    return FailureCandidate(
        candidate_id=candidate_id,
        evidence_id=evidence.evidence_id,
        source=evidence.source,
        predicted_kind=predicted_kind,
        features=features,
        evidence_event_ids=ordered_event_ids,
        feedback_ids=tuple(item.annotation_id for item in feedback_list),
        dataset_version=dataset_version,
    )


def extract_candidates(
    traces: Iterable[TraceEvidence],
    feedback_by_trace: dict[str, tuple[FeedbackAnnotation, ...]] | None = None,
    *,
    dataset_version: int | None = None,
) -> tuple[FailureCandidate, ...]:
    """Extract and sort candidates for a deterministic dataset run."""
    feedback_by_trace = feedback_by_trace or {}
    candidates = [
        candidate
        for evidence in traces
        if (
            candidate := extract_failure_candidate(
                evidence,
                feedback_by_trace.get(evidence.source.trace_id, ()),
                dataset_version=dataset_version,
            )
        )
        is not None
    ]
    return tuple(sorted(candidates, key=lambda item: str(item.evidence_id)))


__all__ = ["extract_candidates", "extract_failure_candidate"]
