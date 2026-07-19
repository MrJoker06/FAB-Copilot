from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Literal


ResolutionStrategy = Literal[
    "none",
    "ordinal_selection",
    "continue_previous_action",
    "general_scope_correction",
    "diagnostic_followup",
    "topic_followup",
    "history_recall",
]


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
_GENERAL_SCOPE_PATTERN = re.compile(
    r"(?:不涉及|不需要|无需).{0,12}(?:具体工艺|具体制程|具体制造|制造分析|生产数据|厂内数据|设备数据)|"
    r"(?:只|仅).{0,8}(?:通用问题|通用知识|概念|原理)|"
    r"(?:仅仅|只是|就只是|只|仅).{0,8}(?:用于)?科普|直接回答|直接解释"
)
_DIAGNOSTIC_FOLLOWUP_PATTERN = re.compile(
    r"^(?:(?:基于|结合)(?:这些|上述|上面)?(?:数据|结果|分析))?"
    r"(?:请|再|还|能否|可以)?.{0,6}(?:给出|提供|说说)?"
    r"(?:什么|哪些)?.{0,4}(?:改进|改善|优化|提升)(?:建议|方向|机会|空间|优先级)?[。！!？?]*$|"
    r"^(?:还有|有|存在|请指出)?.{0,4}(?:什么|哪些)(?:风险|问题|异常|瓶颈|短板)"
    r"(?:(?:和|与|及|、)(?:风险|问题|异常|瓶颈|短板))?[。！!？?]*$"
)
_TOPIC_FOLLOWUP_PATTERN = re.compile(
    r"^(?:(?:需要|希望|请|能否|可以)?(?:再|继续|进一步|更)(?:详细|深入|具体)?(?:地)?"
    r"(?:说|讲|说明|解释|回答|分析|展开|介绍)?(?:一下|一些|一点|点|(?:的)?内容)?|"
    r"(?:详细|深入|具体)(?:一点|一些|说说|讲讲|说明|解释|展开)(?:一下)?|"
    r"(?:展开|补充)(?:说说|讲讲|说明|解释)?(?:一下)?|"
    r"(?:再)?(?:举|给)(?:几个|一个|些)?例子|"
    r"(?:那|那么)?(?:为什么|怎么理解|然后呢|还有呢)|"
    r"(?:换个角度|重新)(?:说|讲|说明|解释)(?:一下)?|"
    r"(?:继续|接着)(?:这个|该|上面|之前)?(?:问题|内容|话题)|"
    r"(?:关于)?(?:之前|刚才|上面|上述|前面|原来|上一个)(?:的)?(?:问题|内容|回答|话题)"
    r".{0,20}(?:进一步|继续|补充|展开|详细|回答|说明|解释).*)[。！!？?]*$"
)
_HISTORY_RECALL_PATTERN = re.compile(
    r"^(?:你(?:还)?(?:记得|知道))?.{0,6}(?:我)?(?:刚才|之前|前面|上一个)"
    r"(?:问|说|提到)(?:的)?(?:问题|内容|话题)?(?:是)?(?:什么|啥)(?:吗)?[。！!？?]*$|"
    r"^(?:我)?(?:刚才|之前|前面|上一个)(?:问|说|提到)(?:的)?(?:是)?(?:什么|啥)[。！!？?]*$"
)
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
        if (
            content
            and not _CONTINUATION_PATTERN.fullmatch(content)
            and not _LAST_PATTERN.search(content)
            and not _GENERAL_SCOPE_PATTERN.search(content)
            and not _DIAGNOSTIC_FOLLOWUP_PATTERN.fullmatch(content)
            and not _TOPIC_FOLLOWUP_PATTERN.fullmatch(content)
            and not _HISTORY_RECALL_PATTERN.fullmatch(content)
        ):
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


def _resolve_general_scope(question: str, history: list[dict]) -> ContextResolution | None:
    normalized = _plain(question, 200)
    if not _GENERAL_SCOPE_PATTERN.search(normalized):
        return None
    base = _base_user_question(history)
    if not base:
        return None
    selected = "直接回答原知识问题，不查询或推断厂内生产数据，并先检索个人知识和工厂知识"
    return ContextResolution(
        question,
        f"{base}；用户明确要求{selected}。",
        True,
        "general_scope_correction",
        selected,
    )


def _resolve_diagnostic_followup(question: str, history: list[dict]) -> ContextResolution | None:
    normalized = _plain(question, 200)
    if not _DIAGNOSTIC_FOLLOWUP_PATTERN.fullmatch(normalized):
        return None
    base = _base_user_question(history)
    if not base:
        return None
    selected = "基于上一问题对应的制造数据识别风险、瓶颈和改善优先级"
    return ContextResolution(
        question,
        f"{base}；用户继续要求{selected}。",
        True,
        "diagnostic_followup",
        selected,
    )


def _resolve_history_recall(question: str, history: list[dict]) -> ContextResolution | None:
    normalized = _plain(question, 200)
    if not _HISTORY_RECALL_PATTERN.fullmatch(normalized):
        return None
    base = _base_user_question(history)
    if not base:
        return None
    return ContextResolution(question, question, True, "history_recall", base)


def _resolve_topic_followup(question: str, history: list[dict]) -> ContextResolution | None:
    normalized = _plain(question, 200)
    if not _TOPIC_FOLLOWUP_PATTERN.fullmatch(normalized):
        return None
    base = _base_user_question(history)
    if not base:
        return None
    return ContextResolution(
        question,
        f"{base}；这是同一会话的连续追问，用户当前要求：{normalized}",
        True,
        "topic_followup",
        base,
    )


def resolve_question_context(question: str, history: list[dict] | None = None) -> ContextResolution:
    normalized = _plain(question, 4000)
    items = list(history or [])
    resolution = (
        _resolve_history_recall(normalized, items)
        or _resolve_ordinal(normalized, items)
        or _resolve_continuation(normalized, items)
        or _resolve_general_scope(normalized, items)
        or _resolve_diagnostic_followup(normalized, items)
        or _resolve_topic_followup(normalized, items)
    )
    return resolution or ContextResolution(question, question, False, "none", "")


def context_system_message(resolution: ContextResolution) -> str:
    return (
        "当前用户输入是依赖上文的短追问。以下 resolved_question 由确定性规则从最近会话中的"
        "用户原问题、澄清选项或助手已声明任务组合得到，仅用于恢复用户指代，不是制造事实或证据。"
        "回答当前用户时应直接完成 resolved_question，不要再次承诺稍后调用工具，也不要展示伪工具 JSON。\n"
        f"context_resolution={json.dumps(resolution.to_dict(), ensure_ascii=False, separators=(',', ':'))}"
    )
