"""Ready-plan result projection applied inside the dispatcher adoption boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

from ..tools.contracts import ToolExecutionLimits, ToolResult


@dataclass(slots=True)
class ReadyResultPolicy:
    knowledge_tools: frozenset[str] = frozenset()
    usable_knowledge_result: Callable[[str, dict[str, object]], bool] | None = None
    _raw_rows: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.knowledge_tools, frozenset) or any(
            not isinstance(name, str) or not name for name in self.knowledge_tools
        ):
            raise ValueError("knowledge_tools must be a frozenset of names")
        if self.knowledge_tools and not callable(self.usable_knowledge_result):
            raise ValueError("knowledge tools require usable_knowledge_result")
        if (
            not self.knowledge_tools
            and self.usable_knowledge_result is not None
            and not callable(self.usable_knowledge_result)
        ):
            raise ValueError("usable_knowledge_result must be callable")

    def finalize(
        self,
        result: ToolResult[object],
        arguments: Mapping[str, object],
        limits: ToolExecutionLimits,
    ) -> ToolResult[object]:
        data = result.data
        raw_rows = (
            len(data) if isinstance(data, (list, tuple)) else (0 if data is None else 1)
        )
        self._raw_rows[result.call_id] = raw_rows
        projected = data
        if result.tool_name in self.knowledge_tools:
            query = str(arguments.get("query") or "")
            usable = self.usable_knowledge_result
            projected = (
                [
                    item
                    for item in data
                    if isinstance(item, dict)
                    and usable is not None
                    and usable(query, item)
                ]
                if isinstance(data, list)
                else []
            )
        if isinstance(projected, list) and limits.max_result_rows is not None:
            projected = projected[: limits.max_result_rows]
        rows = (
            len(projected)
            if isinstance(projected, (list, tuple))
            else (0 if projected is None else 1)
        )
        return replace(result, data=projected, row_count=rows)

    def take_raw_rows(self, call_id: str) -> int | None:
        return self._raw_rows.pop(call_id, None)

    def extract_sources(
        self, result: ToolResult[object]
    ) -> tuple[dict[str, object], ...]:
        if result.tool_name not in self.knowledge_tools or not isinstance(
            result.data, list
        ):
            return ()
        return tuple(
            item
            for item in result.data
            if isinstance(item, dict) and str(item.get("reference_id") or "")
        )

    def clear(self) -> None:
        self._raw_rows.clear()
