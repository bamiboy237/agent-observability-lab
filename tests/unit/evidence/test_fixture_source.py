"""This module tests the local fixture source for checkpoint 3.2.

The fixture source and fake provider sources implement the same contract.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.adapters.sources.fixture_source import FixtureTraceSource
from app.domain.evidence.errors import TraceNotFound
from app.domain.evidence.source import MAX_COHORT_LIMIT, TraceQuery

FIXTURE_TRACE_IDS = (
    "phase2-01-bad-prompt-policy-answer",
    "phase2-02-wrong-policy-evidence",
    "phase2-03-database-timeout",
    "phase2-04-wrong-tool-arguments",
    "phase2-05-unconfirmed-refund",
    "phase2-06-repeated-step",
    "phase2-07-slow-database",
    "phase2-08-model-cost-comparison-candidate",
    "phase2-08-model-cost-comparison-primary",
)


async def test_fixture_source_serves_every_scenario_fixture() -> None:
    source = FixtureTraceSource()
    assert source.available_trace_ids() == FIXTURE_TRACE_IDS
    for trace_id in FIXTURE_TRACE_IDS:
        evidence = await source.fetch_trace(trace_id)
        assert evidence.source.trace_id == trace_id
        assert evidence.events


async def test_fixture_source_returns_not_found_for_unknown_trace() -> None:
    with pytest.raises(TraceNotFound):
        await FixtureTraceSource().fetch_trace("phase2-99-does-not-exist")


async def test_fixture_source_cohort_is_bounded_by_limit() -> None:
    source = FixtureTraceSource()
    cohort = await source.fetch_traces(TraceQuery(limit=3))
    assert len(cohort) == 3


async def test_fixture_source_cohort_filters_by_model() -> None:
    source = FixtureTraceSource()
    cohort = await source.fetch_traces(
        TraceQuery(limit=MAX_COHORT_LIMIT, model_name="gpt-4.1-mini")
    )
    assert [evidence.source.trace_id for evidence in cohort] == [
        "phase2-08-model-cost-comparison-candidate"
    ]


async def test_fixture_source_cohort_filters_by_workflow_config_version() -> None:
    source = FixtureTraceSource()
    cohort = await source.fetch_traces(
        TraceQuery(limit=MAX_COHORT_LIMIT, workflow="support_agent", config_version="2.0.0")
    )
    assert len(cohort) == len(FIXTURE_TRACE_IDS)


async def test_fixture_source_cohort_filters_by_time_window() -> None:
    source = FixtureTraceSource()
    since = datetime(2026, 8, 4, 10, 4, tzinfo=timezone.utc)
    until = datetime(2026, 8, 4, 10, 7, tzinfo=timezone.utc)
    cohort = await source.fetch_traces(TraceQuery(limit=MAX_COHORT_LIMIT, since=since, until=until))
    assert {evidence.source.trace_id for evidence in cohort} == {
        "phase2-04-wrong-tool-arguments",
        "phase2-05-unconfirmed-refund",
    }


async def test_fixture_source_returns_no_matches_for_environment_filter() -> None:
    source = FixtureTraceSource()
    cohort = await source.fetch_traces(TraceQuery(limit=5, environment="production"))
    assert cohort == []


def test_trace_query_rejects_zero_limit() -> None:
    with pytest.raises(ValidationError):
        TraceQuery(limit=0)


def test_trace_query_rejects_unbounded_limit() -> None:
    with pytest.raises(ValidationError):
        TraceQuery(limit=MAX_COHORT_LIMIT + 1)


def test_trace_query_rejects_inverted_time_window() -> None:
    with pytest.raises(ValidationError, match="until"):
        TraceQuery(
            since=datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
            until=datetime(2026, 8, 4, 10, tzinfo=timezone.utc),
        )


def test_trace_query_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        TraceQuery.model_validate({"limit": 1, "secret_field": "x"})
