"""Shared in-memory fakes for repository and use-case tests."""

from typing import Any


class FakeSqlExecutor:
    """Records executed statements and returns queued rows for fetch_one."""

    def __init__(self, fetch_one_results: list[dict[str, Any] | None] | None = None) -> None:
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self._fetch_one_results = list(fetch_one_results or [])

    async def fetch_one(self, query: str, values: dict) -> dict[str, Any] | None:
        self.queries.append((query, values))
        if self._fetch_one_results:
            return self._fetch_one_results.pop(0)
        return None

    async def fetch_all(self, query: str, values: dict) -> list[dict[str, Any]]:
        self.queries.append((query, values))
        return []

    async def execute(self, query: str, values: dict) -> None:
        self.queries.append((query, values))
