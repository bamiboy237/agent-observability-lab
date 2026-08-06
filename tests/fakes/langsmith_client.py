"""This module provides a fake LangSmith API client for unit tests."""

from collections.abc import Callable
from typing import Any

import httpx

from app.domain.evidence.source import TraceQuery


class FakeLangSmithClient:
    """This fake serves recorded run trees or raises configured HTTP failures."""

    def __init__(
        self,
        run_trees: dict[str, dict[str, Any]] | None = None,
        query_results: list[dict[str, Any]] | None = None,
        error_factory: Callable[[], Exception] | None = None,
    ) -> None:
        self.run_trees = run_trees or {}
        self.query_results = query_results or []
        self.error_factory = error_factory
        self.fetch_calls: list[str] = []
        self.query_calls: list[TraceQuery] = []
        self.closed = False

    @staticmethod
    def status_error(status_code: int) -> httpx.HTTPStatusError:
        request = httpx.Request("GET", "https://api.smith.langchain.com/runs/x")
        response = httpx.Response(status_code, request=request)
        return httpx.HTTPStatusError(
            "request failed",
            request=request,
            response=response,
        )

    async def fetch_run_tree(self, run_id: str) -> dict[str, Any]:
        self.fetch_calls.append(run_id)
        if self.error_factory is not None:
            raise self.error_factory()
        tree = self.run_trees.get(run_id)
        if tree is None:
            raise self.status_error(404)
        return tree

    async def query_root_runs(self, query: TraceQuery) -> list[dict[str, Any]]:
        self.query_calls.append(query)
        if self.error_factory is not None:
            raise self.error_factory()
        return self.query_results

    async def close(self) -> None:
        self.closed = True
