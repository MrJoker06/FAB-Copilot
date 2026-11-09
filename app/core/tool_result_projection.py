"""Bound tool results before they are rendered into the synthesis prompt.

Cpk-style diagnostic plans execute up to seven tools, several of which return one
hundred rows.  The combined JSON then exceeds a 40960-token llama.cpp slot and the
whole answer degrades to "model unavailable".  Truncation happens only on the
prompt view: the observations, the validator counts, the run record and the API
responses keep the full data, so evidence metrics such as ``small_sample`` are
unaffected.

Every truncation is reported twice: per evidence entry (``total_rows`` /
``shown_rows`` for the model) and once in the answer limitations (for the user).

This is a pure stdlib projection helper, so orchestration stages may import it
without taking an evidence-layer dependency.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolLimit:
    """How many rows of one tool are worth showing to the model."""

    rows: int
    sort_label: str
    keep_fields: tuple[str, ...] | None = None


TOOL_LIMITS: dict[str, ToolLimit] = {
    "get_sensor_summary": ToolLimit(15, "异常点从多到少"),
    "get_recent_excursions": ToolLimit(20, "按发生时间倒序"),
    "get_equipment_excursion_history": ToolLimit(20, "按发生时间倒序"),
    "get_equipment_event_timeline": ToolLimit(20, "按事件时间倒序"),
    "get_equipment_health": ToolLimit(10, "Critical 优先"),
    "get_equipment_productivity": ToolLimit(10, "利用率从低到高"),
    "search_knowledge": ToolLimit(
        3,
        "检索得分顺序",
        keep_fields=(
            "source_type",
            "reference_id",
            "title",
            "source",
            "section",
            "excerpt",
            "process_step",
            "equipment_id",
            "severity",
            "occurred_date",
            "problem",
            "solution",
            "root_cause",
            "root_cause_confidence",
            "case_status",
        ),
    ),
}

_HEALTH_RANK = {"critical": 0, "warning": 1, "degraded": 1, "healthy": 2}


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""


def _number(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key)
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def _health_key(row: Mapping[str, Any]) -> tuple[int, float]:
    rank = _HEALTH_RANK.get(_text(row, "health").lower(), 3)
    return rank, -_number(row, "excursions")


def _time_desc(row: Mapping[str, Any], key: str) -> tuple[str, str]:
    return (_text(row, key), "")


SORTERS: dict[str, Callable[[list[dict[str, Any]]], list[dict[str, Any]]]] = {
    "get_sensor_summary": lambda rows: sorted(rows, key=lambda row: _number(row, "flagged_outliers"), reverse=True),
    "get_recent_excursions": lambda rows: sorted(rows, key=lambda row: _time_desc(row, "run_time"), reverse=True),
    "get_equipment_excursion_history": lambda rows: sorted(rows, key=lambda row: _time_desc(row, "run_time"), reverse=True),
    "get_equipment_event_timeline": lambda rows: sorted(rows, key=lambda row: _time_desc(row, "event_time"), reverse=True),
    "get_equipment_health": lambda rows: sorted(rows, key=_health_key),
    "get_equipment_productivity": lambda rows: sorted(rows, key=lambda row: _number(row, "productive_pct")),
}


def project_result(tool: str, result: Any) -> tuple[Any, dict[str, Any] | None]:
    """Return ``(prompt_view, truncation_meta)`` for one successful tool result.

    ``truncation_meta`` is ``None`` when the result fits the limit unchanged.
    """
    limit = TOOL_LIMITS.get(tool)
    if limit is None or not isinstance(result, list) or len(result) <= limit.rows:
        return result, None

    rows = [row for row in result if isinstance(row, dict)]
    if len(rows) != len(result):
        return result, None

    sorter = SORTERS.get(tool)
    ordered = sorter(rows) if sorter is not None else rows
    shown = ordered[: limit.rows]
    if limit.keep_fields is not None:
        shown = [
            {key: row[key] for key in limit.keep_fields if key in row}
            for row in shown
        ]

    meta = {
        "total_rows": len(result),
        "shown_rows": len(shown),
        "sort": limit.sort_label,
    }
    return shown, meta


def truncation_details(observations: Sequence[Any]) -> list[dict[str, Any]]:
    """Return one entry per tool whose successful result exceeds its limit."""
    details: list[dict[str, Any]] = []
    for item in observations:
        if str(getattr(item, "status", "") or "") != "success":
            continue
        tool = str(getattr(item, "tool", "") or "")
        result = getattr(item, "result", None)
        limit = TOOL_LIMITS.get(tool)
        if limit is None or not isinstance(result, list) or len(result) <= limit.rows:
            continue
        details.append(
            {
                "tool": tool,
                "shown_rows": limit.rows,
                "total_rows": len(result),
                "sort": limit.sort_label,
            }
        )
    return details


def truncation_notices(observations: Sequence[Any]) -> list[str]:
    """Collect "N/total" summaries for every tool result that would be truncated."""
    details = truncation_details(observations)
    if not details:
        return []
    parts = "、".join(
        f"{item['tool']} {item['shown_rows']}/{item['total_rows']}"
        for item in sorted(details, key=lambda entry: entry["tool"])
    )
    return [f"为控制上下文，以下工具结果已裁剪：{parts}；完整结果保留在运行记录中。"]


def truncation_prompt_note(tool: str, meta: Mapping[str, Any]) -> str:
    """Sentence the model sees next to a truncated evidence entry."""
    return (
        f"仅展示 {meta['shown_rows']}/{meta['total_rows']} 条（{meta['sort']}），"
        "不得据此推断未展示的记录不存在。"
    )


def prompt_content(tool: str, result: Any) -> str:
    """Render a tool result for the model prompt, with its truncation metadata."""
    view, meta = project_result(tool, result)
    payload: dict[str, Any] = {"ok": True, "data": view}
    if meta is not None:
        payload["truncation"] = dict(meta, note=truncation_prompt_note(tool, meta))
    return json.dumps(payload, ensure_ascii=False, default=str)
