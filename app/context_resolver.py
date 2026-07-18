from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Literal


ResolutionStrategy = Literal["none", "ordinal_selection", "continue_previous_action"]


@dataclass(frozen=True)
class ContextResolution:
    original_question: str
    resolved_question: str
    applied: bool
    strategy: ResolutionStrategy
    selected_context: str

    def to_dict(self) -> dict:
        return asdict(self)


_BULLET_PATTERN = re.compile(
    r"^\s*(?:[-*•]|\d+[.)、]|[一二三四五六七八九十]+[、.)])\s*(.+?)\s*$"
)
_ORDINAL_PATTERN = re.compile(r"第\s*([一二三四五六七八九十两\d]+)\s*(?:点|项|个)")
_LAST_PATTERN = re.compile(r"(?:最后|末尾)(?:一)?(?:点|项|个)")
_CONTINUATION_PATTERN = re.compile(
    r"^(?:请)?(?:继续|接着|往下)(?:说|查|查询|分析|执行|进行)?(?:一下)?[。！!？?]*$|"
    r"^(?:为什么|怎么|为何)(?:还)?没有继续[。！!？?]*$"
)
_ACTION_PATTERN = re.compile(r"(?:调用|查询|查找|检索|分析|执行|开始|继续|接下来|我先)")
_MARKDOWN_PATTERN = re.compile(r"[*_`#]+")


def _plain(value: str, limit: int = 1200) -> str:
    return " ".join(_MARKDOWN_PATTERN.sub("", value).strip().split())[:limit]


def _options(content: str) -> list[str]:
    options: list[str] = []
    for line in content.splitlines():
        match = _BULLET_PATTERN.match(line)
        if not match:
            continue
        option = _plain(match.group(1), 500)
        if option:
            options.append(option)
    return options


def _number(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "十" in value:
        tens, _, ones = value.partition("十")
        return digits.get(tens, 1) * 10 + digits.get(ones, 0)
    return digits.get(value)


def _base_user_question(history: list[dict], before: int | None = None) -> str:
    boundary = len(history) if before is None else before
    for item in reversed(history[:boundary]):
        if item.get("role") != "user":
            continue
        content = _plain(str(item.get("content") or ""), 600)
        if content and not _CONTINUATION_PATTERN.fullmatch(content) and not _LAST_PATTERN.search(content):
            return content
    return ""


def _resolve_ordinal(question: str, history: list[dict]) -> ContextResolution | None:
    ordinal = _ORDINAL_PATTERN.search(question)
    is_last = bool(_LAST_PATTERN.search(question))
    if not ordinal and not is_last:
        return None
    for index in range(len(history) - 1, -1, -1):
        item = history[index]
        if item.get("role") != "assistant":
            continue
        options = _options(str(item.get("content") or ""))
        if not options:
            continue
        selected_index = len(options) - 1 if is_last else (_number(ordinal.group(1)) or 0) - 1
        if not 0 <= selected_index < len(options):
            return None
        selected = options[selected_index]
        base = _base_user_question(history, index)
        resolved = f"{base}；用户选择的分析方向：{selected}" if base else selected
        return ContextResolution(question, resolved, True, "ordinal_selection", selected)
    return None


def _resolve_continuation(question: str, history: list[dict]) -> ContextResolution | None:
    normalized = _plain(question, 100)
    if not _CONTINUATION_PATTERN.fullmatch(normalized):
        return None
    last_assistant = ""
    for item in reversed(history):
        if item.get("role") != "assistant":
            continue
        candidate = _plain(str(item.get("content") or ""), 800)
        if candidate and _ACTION_PATTERN.search(candidate):
            last_assistant = candidate
            break
    if not last_assistant:
        return None
    base = _base_user_question(history)
    resolved = f"{base}；继续执行上一条助手已声明的任务：{last_assistant}" if base else last_assistant
    return ContextResolution(question, resolved, True, "continue_previous_action", last_assistant)


def resolve_question_context(question: str, history: list[dict] | None = None) -> ContextResolution:
    normalized = _plain(question, 4000)
    items = list(history or [])
    resolution = _resolve_ordinal(normalized, items) or _resolve_continuation(normalized, items)
    return resolution or ContextResolution(question, question, False, "none", "")


def context_system_message(resolution: ContextResolution) -> str:
    return (
        "当前用户输入是依赖上文的短追问。以下 resolved_question 由确定性规则从最近会话中的"
        "用户原问题、澄清选项或助手已声明任务组合得到，仅用于恢复用户指代，不是制造事实或证据。"
        "回答当前用户时应直接完成 resolved_question，不要再次承诺稍后调用工具，也不要展示伪工具 JSON。\n"
        f"context_resolution={json.dumps(resolution.to_dict(), ensure_ascii=False, separators=(',', ':'))}"
    )
