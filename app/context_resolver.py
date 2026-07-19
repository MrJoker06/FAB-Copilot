from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Literal


ResolutionStrategy = Literal[
    "none",
    "ordinal_selection",
    "semantic_followup",
    "semantic_correction",
    "semantic_recall",
]
ContextRelation = Literal["standalone", "followup", "correction", "recall"]
ResolutionSource = Literal["none", "deterministic", "model", "fallback"]


@dataclass(frozen=True)
class ContextResolution:
    original_question: str
    resolved_question: str
    applied: bool
    strategy: ResolutionStrategy
    selected_context: str
    relation: ContextRelation = "standalone"
    confidence: float = 1.0
    source: ResolutionSource = "none"

    def to_dict(self) -> dict:
        return asdict(self)


_BULLET_PATTERN = re.compile(
    r"^\s*(?:[-*•]|\d+[.)、]|[一二三四五六七八九十]+[、.)])\s*(.+?)\s*$"
)
_ORDINAL_PATTERN = re.compile(
    r"^(?:选择|选|就)?\s*第\s*([一二三四五六七八九十两\d]+)\s*(?:点|项|个)\s*(?:吧|即可)?[。！!？?]*$"
)
_LAST_PATTERN = re.compile(
    r"^(?:选择|选|就)?\s*(?:最后|末尾)(?:一)?(?:点|项|个)\s*(?:吧|即可)?[。！!？?]*$"
)
_MARKDOWN_PATTERN = re.compile(r"[*_`#]+")

CONTEXTUALIZE_TURN_TOOL = {
    "type": "function",
    "function": {
        "name": "resolve_conversation_turn",
        "description": "根据当前会话历史判断本轮输入是否依赖上文，并生成可独立理解的问题。",
        "parameters": {
            "type": "object",
            "properties": {
                "relation": {
                    "type": "string",
                    "enum": ["standalone", "followup", "correction", "recall"],
                    "description": "当前输入与历史的语义关系。",
                },
                "resolved_question": {
                    "type": "string",
                    "description": "不依赖聊天记录也能完整理解的当前问题；独立问题保持原意。",
                },
                "topic_anchor": {
                    "type": "string",
                    "description": "本轮引用的历史主题；独立问题留空。",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "关系判断的置信度。",
                },
            },
            "required": ["relation", "resolved_question", "topic_anchor", "confidence"],
            "additionalProperties": False,
        },
    },
}

CONTEXTUALIZER_PROMPT = """你是 Agent Loop 的会话上下文解析器，不负责回答用户问题。

读取最近会话和本轮输入后，必须调用 resolve_conversation_turn，并遵守：
1. standalone：本轮是完整的新问题，resolved_question 保持本轮原意，不拼接旧主题。
2. followup：本轮省略了对象、条件或动作，需要从最近相关历史补全。
3. correction：本轮修改、替换或限制了上一问题，补全后必须体现修改，而不是保留被否定的要求。
4. recall：用户询问此前说过或问过什么，topic_anchor 填写被询问的历史内容。
5. resolved_question 必须是可直接进入意图路由的完整任务，保留用户当前比较对象、范围和目标。
6. 只能恢复会话指代，禁止添加历史中不存在的制造事实、参数、结论或证据。
7. 不输出分析过程、解释或答案，只调用指定函数。"""


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


def _previous_user_question(history: list[dict], before: int | None = None) -> str:
    boundary = len(history) if before is None else before
    for item in reversed(history[:boundary]):
        if item.get("role") != "user":
            continue
        content = _plain(str(item.get("content") or ""), 1000)
        if content:
            return content
    return ""


def _resolve_ordinal(question: str, history: list[dict]) -> ContextResolution | None:
    ordinal = _ORDINAL_PATTERN.fullmatch(question)
    is_last = bool(_LAST_PATTERN.fullmatch(question))
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
        base = _previous_user_question(history, index)
        resolved = f"{base}；用户选择的分析方向：{selected}" if base else selected
        return ContextResolution(
            question,
            resolved,
            True,
            "ordinal_selection",
            selected,
            relation="followup",
            confidence=1.0,
            source="deterministic",
        )
    return None


def unresolved_context(question: str, source: ResolutionSource = "none") -> ContextResolution:
    return ContextResolution(question, question, False, "none", "", source=source)


def resolve_question_context(question: str, history: list[dict] | None = None) -> ContextResolution:
    """Resolve only structurally unambiguous UI selections without an LLM call."""
    normalized = _plain(question, 4000)
    resolution = _resolve_ordinal(normalized, list(history or []))
    return resolution or unresolved_context(question)


def build_contextualizer_messages(
    question: str,
    history: list[dict] | None,
    *,
    message_limit: int = 20,
    character_budget: int = 16_000,
) -> list[dict]:
    candidates: list[dict] = []
    remaining = character_budget
    for item in reversed(list(history or [])[-message_limit:]):
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        per_message_limit = 1600 if role == "assistant" else 1000
        content = _plain(str(item.get("content") or ""), per_message_limit)
        if not content or remaining <= 0:
            continue
        content = content[:remaining]
        remaining -= len(content)
        candidates.append({"role": role, "content": content})
    candidates.reverse()
    return [
        {"role": "system", "content": CONTEXTUALIZER_PROMPT},
        *candidates,
        {"role": "user", "content": _plain(question, 4000)},
    ]


def semantic_context_resolution(question: str, arguments: dict) -> ContextResolution:
    relation = str(arguments.get("relation") or "").strip()
    if relation not in {"standalone", "followup", "correction", "recall"}:
        return unresolved_context(question, "fallback")
    try:
        confidence = max(0.0, min(float(arguments.get("confidence", 0)), 1.0))
    except (TypeError, ValueError):
        return unresolved_context(question, "fallback")
    resolved = _plain(str(arguments.get("resolved_question") or ""), 4000)
    topic_anchor = _plain(str(arguments.get("topic_anchor") or ""), 1200)
    if relation == "standalone" or confidence < 0.65:
        return ContextResolution(
            question,
            question,
            False,
            "none",
            "",
            relation="standalone" if relation == "standalone" else relation,
            confidence=confidence,
            source="model",
        )
    if not resolved or (relation == "recall" and not topic_anchor):
        return unresolved_context(question, "fallback")
    strategies: dict[str, ResolutionStrategy] = {
        "followup": "semantic_followup",
        "correction": "semantic_correction",
        "recall": "semantic_recall",
    }
    return ContextResolution(
        question,
        resolved,
        True,
        strategies[relation],
        topic_anchor,
        relation=relation,
        confidence=confidence,
        source="model",
    )


def context_system_message(resolution: ContextResolution) -> str:
    return (
        "当前输入依赖会话历史。context_resolution 是独立的语义上下文阶段产生的结构化结果，"
        "只用于恢复指代或用户修正，不是制造事实、证据或隐藏思维链。"
        "回答时完成 resolved_question，仍须通过正常工具和证据约束验证事实。\n"
        f"context_resolution={json.dumps(resolution.to_dict(), ensure_ascii=False, separators=(',', ':'))}"
    )
