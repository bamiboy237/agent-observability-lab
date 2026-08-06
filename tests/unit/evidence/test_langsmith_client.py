"""This module tests the LangSmith HTTP client against the verified API shapes.

The client talks through an httpx mock transport. The request shapes here
match what the live LangSmith API accepted during the credential-gated check.
"""

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.adapters.sources.langsmith import LangSmithClient, LangSmithSourceConfig
from app.domain.evidence.errors import TraceNotFound, TraceSourceUnavailable
from app.domain.evidence.source import TraceQuery

PROJECT_ID = "5630d6ac-15d8-4db1-8d8f-b433138b87c8"


def _config() -> LangSmithSourceConfig:
    return LangSmithSourceConfig(
        api_key=SecretStr("sk-live-test"),
        project="agent-replay",
    )


def _run_dict(run_id: str, parent_id: str | None = None) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": "support_agent.turn" if parent_id is None else "support_agent.answer",
        "parent_run_id": parent_id,
        "start_time": "2026-08-05T23:33:25.000Z",
        "end_time": "2026-08-05T23:33:27.000Z",
        "run_type": "chain",
        "trace_id": "root-1",
        "error": None,
        "extra": {"metadata": {}},
    }


def _wrapped(runs: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"runs": runs, "cursors": {"next": None, "prev": None}})


def _handler(*, requests: list[dict[str, Any]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "body": request.content.decode() if request.content else None,
            }
        )
        if request.url.path == "/sessions":
            return httpx.Response(200, json=[{"id": PROJECT_ID, "name": "agent-replay"}])
        if request.url.path == "/runs/query":
            payload = json.loads(request.content.decode())
            if "session" in payload:
                return _wrapped([_run_dict("root-1"), _run_dict("junk-root")])
            if "id" in payload:
                if payload["id"] == ["missing-run"]:
                    return _wrapped([])
                return _wrapped([_run_dict("root-1")])
            if "trace" in payload:
                return _wrapped([_run_dict("root-1"), _run_dict("child-1", "root-1")])
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


async def test_client_resolves_project_and_queries_bounded_cohort() -> None:
    requests: list[dict[str, Any]] = []
    client = LangSmithClient(_config())
    client._http = httpx.AsyncClient(
        transport=_handler(requests=requests),
        base_url=_config().api_base_url,
    )
    try:
        runs = await client.query_root_runs(TraceQuery(limit=3))
    finally:
        await client.close()

    assert [run["id"] for run in runs] == ["root-1", "junk-root"]
    session_call = next(
        call for call in requests if call["method"] == "GET" and "/sessions" in call["url"]
    )
    assert "name=agent-replay" in session_call["url"]
    query_call = next(call for call in requests if "/runs/query" in call["url"])
    body = json.loads(query_call["body"] or "{}")
    assert body == {"session": [PROJECT_ID], "limit": 30, "is_root": True}


async def test_client_includes_time_window_in_cohort_query() -> None:
    requests: list[dict[str, Any]] = []
    client = LangSmithClient(_config())
    client._http = httpx.AsyncClient(
        transport=_handler(requests=requests),
        base_url=_config().api_base_url,
    )
    try:
        await client.query_root_runs(
            TraceQuery(
                limit=5,
                since=datetime(2026, 8, 5, 23, 0, tzinfo=timezone.utc),
                until=datetime(2026, 8, 6, 23, 0, tzinfo=timezone.utc),
            )
        )
    finally:
        await client.close()

    query_call = next(call for call in requests if "/runs/query" in call["url"])
    body = json.loads(query_call["body"] or "{}")
    assert body["start_time"] == "2026-08-05T23:00:00+00:00"
    assert body["end_time"] == "2026-08-06T23:00:00+00:00"


async def test_client_fetches_every_run_in_selected_trace() -> None:
    requests: list[dict[str, Any]] = []
    client = LangSmithClient(_config())
    client._http = httpx.AsyncClient(
        transport=_handler(requests=requests),
        base_url=_config().api_base_url,
    )
    try:
        tree = await client.fetch_run_tree("root-1")
    finally:
        await client.close()

    assert tree["id"] == "root-1"
    assert tree["child_runs"][0]["id"] == "child-1"
    trace_bodies = [
        json.loads(call["body"] or "{}")["trace"]
        for call in requests
        if "/runs/query" in call["url"] and "trace" in json.loads(call["body"] or "{}")
    ]
    assert trace_bodies == ["root-1"]


async def test_client_missing_run_raises_trace_not_found() -> None:
    requests: list[dict[str, Any]] = []
    client = LangSmithClient(_config())
    client._http = httpx.AsyncClient(
        transport=_handler(requests=requests),
        base_url=_config().api_base_url,
    )
    try:
        with pytest.raises(TraceNotFound):
            await client.fetch_run_tree("missing-run")
    finally:
        await client.close()


async def test_client_malformed_query_response_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = LangSmithClient(_config())
    client._http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=_config().api_base_url,
    )
    try:
        with pytest.raises(TraceSourceUnavailable):
            await client.fetch_run_tree("root-1")
    finally:
        await client.close()
