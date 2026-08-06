"""This module tests adapter portability for checkpoint 3.5.

One recorded Braintrust trace maps through the same core contract.
Downstream measurement code receives the same summary from both providers
without any provider-specific branch.
"""

import pytest

from app.adapters.sources.braintrust import BraintrustRecordedSource
from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.evidence.errors import TraceNotFound
from app.domain.evidence.schemas import EvidenceSummary, summarize_evidence
from app.domain.evidence.source import TraceQuery


async def test_braintrust_recorded_trace_maps_to_valid_evidence() -> None:
    source = BraintrustRecordedSource()
    evidence = await source.fetch_trace("phase2-01-bad-prompt-policy-answer")

    assert evidence.schema_version == "3.0.0"
    assert evidence.source.platform == "braintrust"
    assert evidence.source.project == "agent-reliability-lab"
    assert evidence.outcome.value == "blocked"
    assert evidence.reason_code == "policy_answer_ungrounded"
    assert evidence.events
    assert evidence.tokens.total_tokens == 596


async def test_braintrust_source_returns_not_found_for_unknown_trace() -> None:
    with pytest.raises(TraceNotFound):
        await BraintrustRecordedSource().fetch_trace("phase2-99-does-not-exist")


async def test_downstream_summary_has_no_provider_branches() -> None:
    langsmith_evidence = await FixtureTraceSource().fetch_trace(
        "phase2-01-bad-prompt-policy-answer"
    )
    braintrust_evidence = await BraintrustRecordedSource().fetch_trace(
        "phase2-01-bad-prompt-policy-answer"
    )

    langsmith_summary = summarize_evidence(langsmith_evidence)
    braintrust_summary = summarize_evidence(braintrust_evidence)

    assert isinstance(langsmith_summary, EvidenceSummary)
    assert isinstance(braintrust_summary, EvidenceSummary)
    _assert_equivalent(langsmith_summary, braintrust_summary)


async def test_braintrust_cohort_fetch_matches_same_query() -> None:
    source = BraintrustRecordedSource()
    cohort = await source.fetch_traces(TraceQuery(limit=5, model_name="gpt-5.2"))
    assert len(cohort) == 1
    assert cohort[0].source.platform == "braintrust"

    empty = await source.fetch_traces(TraceQuery(limit=5, model_name="gpt-99"))
    assert empty == []


def _assert_equivalent(first: EvidenceSummary, second: EvidenceSummary) -> None:
    assert first.platform != second.platform
    first_core = first.model_dump(exclude={"platform", "trace_id"})
    second_core = second.model_dump(exclude={"platform", "trace_id"})
    assert first_core == second_core
    assert first.trace_id != second.trace_id
