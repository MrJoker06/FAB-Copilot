"""An explicit saved-result selection never re-runs production queries."""

from __future__ import annotations

import json

from ..planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
)
from .execution.loop_guard import ToolLoopGuard


async def review_saved_result(access, reference, cursor, progress):
    plan = ExecutionPlan(
        "saved-result-review",
        "1",
        "result-access",
        "unsupported",
        "显式复核已保存结果，无业务取证步骤",
        "snapshot_review",
        None,
        None,
        AnalysisScopeContract("session", (), (), ()),
        (),
        (),
        PlanBudget(0, 4, 1, 50, {}, 1, 1),
        (),
        (),
    )
    access.bind(ToolLoopGuard(plan))
    access.begin_synthesis(60)
    arguments = {"result_ref": reference}
    if cursor is not None:
        arguments["cursor"] = cursor
    page = await access.read(arguments)
    if page.get("format") in {"units", "unit_fragment"}:
        fragment_note = "当前是一条过长记录的片段，尚未展示整条记录。\n\n" if page.get("format") == "unit_fragment" else ""
        answer = (
            f"以下为已保存结果，查询时间：{page.get('queried_at') or '未知'}；未重新查询业务来源。\n\n"
            f"原范围：{json.dumps(page.get('scope', {}), ensure_ascii=False)}\n\n"
            f"{fragment_note}"
            f"```json\n{json.dumps(page.get('units', page.get('text')), ensure_ascii=False, indent=2)}\n```\n\n"
            + (
                "当前仅显示一页，可继续查看；这不是最新数据或新的诊断结论。"
                if page.get("has_more")
                else "已到本次快照末页；这不是最新数据或新的诊断结论。"
            )
        )
    else:
        answer = "当前无法读取所选结果。请确认会话、访问权限及后台卸载开关；已有结果不会因关闭开关而被删除。"
    if progress is not None:
        from inspect import isawaitable

        value = progress({"event": "answer_delta", "delta": answer})
        if isawaitable(value):
            await value
    return {
        "answer": answer,
        "mode": "snapshot_review",
        "model": "",
        "tool_trace": [],
        "sources": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "execution_mode": "snapshot_review",
        "loop_guard": access.guard.summary(),
        "tool_result_page": page if page.get("format") else None,
    }
