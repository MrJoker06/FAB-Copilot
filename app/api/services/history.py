"""API adapter for the contextual-memory history port."""
from __future__ import annotations

from typing import Any, Callable


class LiveHistoryReader:
    """Resolve the legacy session reader for every request-time read."""

    def __init__(self, namespace: Callable[[], dict[str, Any]]):
        self._namespace = namespace

    def read(self, session_id: str, limit: int = 20) -> list[dict]:
        reader = self._namespace()["session_history"]
        if limit == 20:
            return reader(session_id)
        return reader(session_id, limit=limit)
