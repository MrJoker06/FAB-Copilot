"""Lot commonality references carried by one chat turn.

The page attaches only an ``analysis_ref``.  The server re-authorizes it for the
current principal before the run starts and gives the model a compact summary
of that fixed version; references a run created or read are taken from the
tool trace, never from model text.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.bootstrap.capability_catalog import tool_allowed
from app.core.lot_commonality_view import CREATE_TOOL, MODEL_VIEWS, summary_view
from app.tools.lot_commonality.contracts import LotCommonalityAccessError
from app.tools.lot_commonality.service import ANALYSIS_REF_RE, LotCommonalityResultError

_UNAVAILABLE = "附带的分析结果已不可读取（已过期、无权访问或所属会话已删除），请重新查询后再提问。"


def attached_question(runtime: Mapping[str, Any], request: Any, principal: Any) -> str:
    """Return the run question, raising before any message is stored when the reference is unusable."""
    reference = getattr(request, "analysis_ref", None)
    if not reference:
        return request.message
    if not tool_allowed(CREATE_TOOL, principal):
        raise runtime["http_problem"](403, "CAPABILITY_DENIED", "当前身份无权使用 Lot 共性分析附件。", False)
    try:
        summary = runtime["lot_commonality_service"]().read(reference, principal)
    except LotCommonalityAccessError as exc:
        raise runtime["http_problem"](403, exc.error_code, exc.detail, False) from None
    except LotCommonalityResultError as exc:
        if exc.error_code == "RESULT_UNAVAILABLE":
            raise runtime["http_problem"](404, exc.error_code, _UNAVAILABLE, False) from None
        raise runtime["http_problem"](503, exc.error_code, exc.detail, True) from None
    view = json.dumps(summary_view(summary), ensure_ascii=False, separators=(",", ":"))
    return (
        f"{request.message}\n\n【页面附带的 Lot 共性分析】服务端已按当前用户校验 analysis_ref={reference}，"
        "以下是该固定版本的精简摘要（JSON）。需要成员或过站明细时，"
        "用 read_lot_commonality_members / read_lot_commonality_records 并传入该 analysis_ref；"
        f"不要重新推断 lot。\n{view}"
    )


def analysis_references(result: Mapping[str, Any], attached: str | None = None) -> list[dict[str, str]]:
    """List the analysis versions this turn used: the attached one, then created or read ones."""
    references: list[dict[str, str]] = []

    def add(reference: object, origin: str) -> None:
        if (
            isinstance(reference, str)
            and ANALYSIS_REF_RE.fullmatch(reference)
            and all(item["analysis_ref"] != reference for item in references)
        ):
            references.append({"analysis_ref": reference, "origin": origin})

    if attached:
        add(attached, "attached")
    trace = result.get("tool_trace")
    for item in trace if isinstance(trace, list) else ():
        if not isinstance(item, Mapping) or item.get("tool") not in MODEL_VIEWS or item.get("tool_status") != "succeeded":
            continue
        if item["tool"] == CREATE_TOOL:
            for source in item.get("sources") or ():
                if isinstance(source, Mapping) and source.get("adapter_id") == "lot_commonality":
                    add(source.get("source_ref"), "created")
        else:
            arguments = item.get("arguments")
            add(arguments.get("analysis_ref") if isinstance(arguments, Mapping) else None, "read")
    return references
