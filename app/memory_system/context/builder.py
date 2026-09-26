"""Stage-specific, pure contextual-memory message fragments."""
from __future__ import annotations

import json

from ..contracts import ContextResolution


def build_stage_memory_messages(
    stage: str, history: list[dict] | None,
) -> list[dict[str, str]]:
    """Return the exact history fragment allowed at a named Agent stage."""
    if stage == "ready_synthesis":
        return []
    if stage != "agent_loop":
        raise ValueError(f"未知的 memory stage: {stage}")
    messages: list[dict[str, str]] = []
    for item in (history or [])[-8:]:
        role = item.get("role")
        content = str(item.get("content", ""))[:4000]
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    return messages


def context_system_message(resolution: ContextResolution) -> str:
    return (
        "当前输入依赖会话历史。context_resolution 是独立的语义上下文阶段产生的结构化结果，"
        "只用于恢复指代或用户修正，不是制造事实、证据或隐藏思维链。"
        "回答时完成 resolved_question，仍须通过正常工具和证据约束验证事实。\n"
        f"context_resolution={json.dumps(resolution.to_dict(), ensure_ascii=False, separators=(',', ':'))}"
    )
