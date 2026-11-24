"""Compact model-facing views of lot commonality tool results.

A creation summary reaches about 200 KB (500 lots, 350 candidates), far beyond a
small model's context.  The model sees counts, the top candidates and explicit
omission counts; the page and the read tools re-read the same fixed version by
``analysis_ref``, so nothing shown here is the only copy of the result.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

CREATE_TOOL = "create_lot_commonality_analysis"
MEMBERS_TOOL = "read_lot_commonality_members"
RECORDS_TOOL = "read_lot_commonality_records"
TOP_CANDIDATES = 10
MAX_ATTENTION_LOTS = 10
MAX_MEMBERS = 40
MAX_RECORD_REFS = 4
MAX_PASSES = 15

SUMMARY_NOTE = (
    "仅列出排序前 10 个候选；排序只反映主组命中数和未知数，不代表根因。"
    "成员与过站明细请按 analysis_ref 调用 read_lot_commonality_members / "
    "read_lot_commonality_records 读取，不要自行推断 lot。"
)


def _items(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _group_view(group: Mapping[str, Any]) -> dict[str, Any]:
    states = _items(group.get("lot_states"))
    attention = [
        {"lot_id": item.get("lot_id"), "state": item.get("state"), "reasons": item.get("reasons") or []}
        for item in states
        if item.get("state") != "complete"
    ]
    return {
        "group_id": group.get("group_id"),
        "name": group.get("name"),
        "role": group.get("role"),
        "input_count": group.get("input_count"),
        "unique_count": group.get("unique_count"),
        "duplicates": list(group.get("duplicates") or [])[:MAX_ATTENTION_LOTS],
        "lot_states": dict(Counter(str(item.get("state")) for item in states)),
        "lots_needing_attention": attention[:MAX_ATTENTION_LOTS],
        "omitted_attention_lots": max(0, len(attention) - MAX_ATTENTION_LOTS),
    }


def summary_view(summary: Mapping[str, Any]) -> dict[str, Any]:
    candidates = _items(summary.get("candidates"))
    scope = summary.get("scope") if isinstance(summary.get("scope"), Mapping) else {}
    source = summary.get("source") if isinstance(summary.get("source"), Mapping) else {}
    return {
        "analysis_ref": summary.get("analysis_ref"),
        "status": summary.get("status"),
        "created_at": summary.get("created_at"),
        "expires_at": summary.get("expires_at"),
        "source": {key: source.get(key) for key in ("source_id", "kind", "timezone", "queried_at")},
        "timezone": summary.get("timezone"),
        "scope": {"time_range": scope.get("time_range"), "cutoff": scope.get("cutoff")},
        "dimensions": summary.get("dimensions"),
        "groups": [_group_view(group) for group in _items(summary.get("groups"))],
        "overlap_lot_count": len(_items(summary.get("overlaps"))),
        "union_unique_count": (summary.get("union") or {}).get("unique_count"),
        "candidate_count": len(candidates),
        "candidates_truncated_by_limit": bool(summary.get("candidates_truncated")),
        "candidates": [
            {
                key: candidate.get(key)
                for key in ("candidate_id", "dimension", "label", "all_shared", "counts")
            }
            for candidate in candidates[:TOP_CANDIDATES]
        ],
        "omitted_candidates": max(0, len(candidates) - TOP_CANDIDATES),
        "view_note": SUMMARY_NOTE,
    }


def members_view(page: Mapping[str, Any]) -> dict[str, Any]:
    members = _items(page.get("members"))
    return {
        "analysis_ref": page.get("analysis_ref"),
        "group_id": page.get("group_id"),
        "query": page.get("query"),
        "counts": page.get("counts"),
        "hit_time_range": page.get("hit_time_range"),
        "members": [
            {
                "lot_id": member.get("lot_id"),
                "status": member.get("status"),
                "record_refs": list(member.get("record_refs") or [])[:MAX_RECORD_REFS],
                "reasons": member.get("reasons") or [],
            }
            for member in members[:MAX_MEMBERS]
        ],
        "omitted_members_on_page": max(0, len(members) - MAX_MEMBERS),
        "page": page.get("page"),
    }


def _pass_view(item: Mapping[str, Any]) -> dict[str, Any]:
    rework = item.get("rework") if isinstance(item.get("rework"), Mapping) else {}
    return {
        "record_ref": item.get("record_ref"),
        "lot_id": item.get("lot_id"),
        "pass_seq": item.get("pass_seq"),
        "operation_key": item.get("operation_key"),
        "equipment_id": item.get("equipment_id"),
        "chambers": [chamber.get("chamber") for chamber in _items(item.get("chambers"))],
        "recipe": item.get("recipe"),
        "track_in_at": item.get("track_in_at"),
        "is_rework": bool(rework.get("is_rework")),
        "missing_fields": item.get("missing_fields") or [],
    }


def records_view(page: Mapping[str, Any]) -> dict[str, Any]:
    passes = _items(page.get("passes"))
    lots = []
    for lot in _items(page.get("lots")):
        coverage = lot.get("coverage") if isinstance(lot.get("coverage"), Mapping) else {}
        lots.append(
            {
                "lot_id": lot.get("lot_id"),
                "wafer_count": lot.get("wafer_count"),
                "candidate_status": lot.get("candidate_status"),
                "coverage": {key: coverage.get(key) for key in ("records", "order", "truncated")},
            }
        )
    return {
        "analysis_ref": page.get("analysis_ref"),
        "group_id": page.get("group_id"),
        "candidate_id": page.get("candidate_id"),
        "lots": lots,
        "passes": [_pass_view(item) for item in passes[:MAX_PASSES]],
        "omitted_passes_on_page": max(0, len(passes) - MAX_PASSES),
        "page": page.get("page"),
    }


MODEL_VIEWS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    CREATE_TOOL: summary_view,
    MEMBERS_TOOL: members_view,
    RECORDS_TOOL: records_view,
}
