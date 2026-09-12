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
    "context_clarification",
]
ContextRelation = Literal["standalone", "followup", "correction", "recall"]
ResolutionSource = Literal["none", "deterministic", "model", "fallback", "circuit_open"]
IntentHint = Literal["conversation", "general_knowledge", "manufacturing_analysis", "unclear"]
ResolutionState = Literal["not_applicable", "resolved", "ambiguous", "unavailable"]


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
    intent_hint: IntentHint = "unclear"
    target_message_ids: tuple[int, ...] = ()
    recalled_messages: tuple[dict, ...] = ()
    candidate_messages: tuple[dict, ...] = ()
    failure_reason: str = ""
    # Kept additive so existing consumers of strategy/applied remain compatible.
    resolution_state: ResolutionState = "not_applicable"
    # Optional action output from the existing contextualizer call. It remains
    # raw here so an invalid optional action cannot discard a valid resolution.
    turn_actions: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["target_message_ids"] = list(self.target_message_ids)
        payload["turn_actions"] = [dict(item) for item in self.turn_actions]
        payload.pop("recalled_messages", None)
        payload.pop("candidate_messages", None)
        return payload


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

CONTEXTUALIZER_RESPONSE_FORMAT = {"type": "json_object"}


class ContextPayloadValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def validate_contextualizer_payload(arguments: object) -> dict:
    """Validate the shared structured-context contract while allowing safe extensions."""
    if not isinstance(arguments, dict):
        raise ContextPayloadValidationError("invalid_object", "上下文解析结果必须是 JSON 对象")
    required_fields = {"relation", "resolved_question", "topic_anchor", "target_message_ids", "confidence", "intent_hint"}
    missing_fields = required_fields - set(arguments)
    if missing_fields:
        raise ContextPayloadValidationError("missing_field", f"上下文解析结果缺少字段：{', '.join(sorted(missing_fields))}")
    relation = arguments["relation"]
    intent_hint = arguments["intent_hint"]
    confidence = arguments["confidence"]
    target_ids = arguments["target_message_ids"]
    valid = (
        isinstance(relation, str) and relation in {"standalone", "followup", "correction", "recall"}
        and isinstance(arguments["resolved_question"], str) and bool(arguments["resolved_question"].strip())
        and isinstance(arguments["topic_anchor"], str)
        and isinstance(target_ids, list) and all(isinstance(item, int) and not isinstance(item, bool) for item in target_ids)
        and isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and 0 <= confidence <= 1
        and isinstance(intent_hint, str) and intent_hint in {"conversation", "general_knowledge", "manufacturing_analysis", "unclear"}
    )
    if not valid:
        raise ContextPayloadValidationError("invalid_field_type", "上下文解析结果字段类型或枚举值非法")
    return arguments

CONTEXTUALIZER_PROMPT = """你是 Agent Loop 的会话上下文解析器，不负责回答用户问题。

读取最近会话和本轮输入后，只返回一个 JSON 对象，不得输出解释或 Markdown。JSON 必须包含：
- relation：standalone、followup、correction、recall 之一。
- resolved_question：可独立理解并进入路由的完整当前问题。
- topic_anchor：本轮引用的历史主题；独立问题使用空字符串。
- target_message_ids：recall 时填写被引用历史消息的 message_id 数组；其他关系使用空数组。
- confidence：0 到 1 之间的数字。
- intent_hint：conversation、general_knowledge、manufacturing_analysis、unclear 之一。
- turn_actions：可选数组。它不是工具调用；仅在可靠时返回 action 对象。

语义规则：
1. standalone：本轮是完整的新问题，resolved_question 保持本轮原意，不拼接旧主题。
2. followup：本轮省略了对象、条件或动作，需要从最近相关历史补全。
3. correction：本轮修改、替换或限制了上一问题，补全后必须体现修改，而不是保留被否定的要求。
4. recall：用户询问此前说过、问过或助手如何理解时，必须从输入中提供的 message_id 选择 target_message_ids；不得自行生成历史内容。若用户说“更前面的一个”，应选择比上次回忆目标更早的相关消息。
5. resolved_question 必须是可直接进入意图路由的完整任务，保留用户当前比较对象、范围和目标。
6. 只能恢复会话指代，禁止添加历史中不存在的制造事实、参数、结论或证据。
7. 只有主题、范围、对象、否定条件或回答方式，而没有独立信息请求的输入，不是 standalone；应与最近尚未完成的用户目标组合为 followup 或 correction。助手重复索要范围不代表用户已经放弃原目标。
8. 用户补充、限制或纠正回答应使用的知识来源时，resolved_question 必须同时保留最近尚未完成的信息目标和本轮来源偏好；不能只保留“查个人知识库”等来源动作。
9. intent_hint 由完整信息目标决定，而不是由来源名称决定。conversation 表示助手身份、能力、问候以及不请求外部技术或制造事实的交互或元问题；general_knowledge 表示概念、原理、分类、比较或行业常识，即使用户要求优先使用个人或工厂知识；manufacturing_analysis 表示需要当前生产、设备、批次、指标或异常数据；无法可靠判断时使用 unclear。
10. turn_actions 的完整形状为 [{"type":"answer_meta","subject":"capabilities","detail":"detailed"}]。允许 type 仅为 answer_meta、acknowledge、route_task、recall_history、clarify；最多三个动作，最多一个主要动作（answer_meta、route_task、recall_history、clarify），acknowledge 可与它组合。answer_meta 仅可使用 identity、capabilities、usage_help、limitations_policy、runtime_status、response_review、social、other 主题和 brief、standard、detailed 粒度。模型优先只生成 answer_meta/acknowledge；route_task、recall_history、clarify 通常由服务端派生。禁止包含工具名、SQL、URL 或自由参数；无把握时省略。
11. 不输出分析过程、解释或答案。"""


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
            intent_hint="unclear",
            resolution_state="resolved",
        )
    return None


def unresolved_context(
    question: str,
    source: ResolutionSource = "none",
    *,
    failure_reason: str = "",
) -> ContextResolution:
    state: ResolutionState = "unavailable" if source in {"fallback", "circuit_open"} else "not_applicable"
    return ContextResolution(
        question, question, False, "none", "", source=source,
        failure_reason=failure_reason, resolution_state=state,
    )


def context_clarification_resolution(
    question: str,
    history: list[dict] | None,
    failure_reason: str,
    *,
    relation: ContextRelation = "followup",
    confidence: float = 0.0,
    intent_hint: IntentHint = "unclear",
) -> ContextResolution:
    indexed, _ = _history_index(history)
    candidates = tuple(
        item
        for item in reversed(indexed)
        if item.get("role") == "user" and _plain(str(item.get("content") or ""), 400)
    )[:3]
    return ContextResolution(
        question,
        question,
        False,
        "context_clarification",
        "",
        relation=relation,
        confidence=confidence,
        source="model",
        intent_hint=intent_hint,
        candidate_messages=candidates,
        failure_reason=failure_reason,
        resolution_state="ambiguous",
    )


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
    bounded_history = list(history or [])[-message_limit:]
    indexed_history = [
        {**item, "message_id": int(item.get("message_id") or index + 1)}
        for index, item in enumerate(bounded_history)
    ]
    for item in reversed(indexed_history):
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        prefix = f"[message_id={item['message_id']}] "
        per_message_limit = 1600 if role == "assistant" else 1000
        content = _plain(str(item.get("content") or ""), per_message_limit)
        if not content or remaining <= len(prefix):
            continue
        content = content[:remaining - len(prefix)]
        remaining -= len(prefix) + len(content)
        candidates.append({
            "role": role,
            "content": f"{prefix}{content}",
        })
    candidates.reverse()
    return [
        {"role": "system", "content": CONTEXTUALIZER_PROMPT},
        *candidates,
        {"role": "user", "content": _plain(question, 4000)},
    ]


def _history_index(history: list[dict] | None) -> tuple[list[dict], dict[int, dict]]:
    indexed = [
        {**item, "message_id": int(item.get("message_id") or index + 1)}
        for index, item in enumerate(list(history or []))
    ]
    return indexed, {item["message_id"]: item for item in indexed}


def _recall_records(history: list[dict] | None, target_ids: tuple[int, ...]) -> tuple[dict, ...]:
    indexed, by_id = _history_index(history)
    selected = {message_id for message_id in target_ids if message_id in by_id}
    positions = {item["message_id"]: index for index, item in enumerate(indexed)}
    for message_id in tuple(selected):
        position = positions[message_id]
        item = indexed[position]
        if item.get("role") == "user" and position + 1 < len(indexed):
            following = indexed[position + 1]
            if following.get("role") == "assistant":
                selected.add(following["message_id"])
        elif item.get("role") == "assistant" and position > 0:
            previous = indexed[position - 1]
            if previous.get("role") == "user":
                selected.add(previous["message_id"])
    return tuple(item for item in indexed if item["message_id"] in selected)


def semantic_context_resolution(
    question: str,
    arguments: dict,
    history: list[dict] | None = None,
) -> ContextResolution:
    relation = str(arguments.get("relation") or "").strip()
    if relation not in {"standalone", "followup", "correction", "recall"}:
        return unresolved_context(question, "fallback", failure_reason="protocol_error")
    try:
        confidence = max(0.0, min(float(arguments.get("confidence", 0)), 1.0))
    except (TypeError, ValueError):
        return unresolved_context(question, "fallback", failure_reason="protocol_error")
    resolved = _plain(str(arguments.get("resolved_question") or ""), 4000)
    topic_anchor = _plain(str(arguments.get("topic_anchor") or ""), 1200)
    raw_target_ids = arguments.get("target_message_ids")
    if not isinstance(raw_target_ids, list) or any(not isinstance(item, int) for item in raw_target_ids):
        return unresolved_context(question, "fallback", failure_reason="protocol_error")
    target_message_ids = tuple(dict.fromkeys(raw_target_ids))
    intent_hint = str(arguments.get("intent_hint") or "").strip()
    if intent_hint not in {"conversation", "general_knowledge", "manufacturing_analysis", "unclear"}:
        return unresolved_context(question, "fallback", failure_reason="protocol_error")
    raw_actions = arguments.get("turn_actions", [])
    # Preserve malformed optional values as a harmless sentinel so the later
    # decision validator can emit a degradation event without invalidating the
    # otherwise valid context resolution.
    allowed_action_fields = {"type", "subject", "detail", "target_intent"}
    turn_actions = (
        tuple(
            item if isinstance(item, dict) and set(item).issubset(allowed_action_fields)
            else {"__invalid__": "turn_action_invalid"}
            for item in raw_actions
        )
        if isinstance(raw_actions, list)
        else (({"__invalid__": "turn_action_invalid"},) if "turn_actions" in arguments else ())
    )
    if relation == "standalone":
        return ContextResolution(
            question,
            question,
            False,
            "none",
            "",
            relation="standalone" if relation == "standalone" else relation,
            confidence=confidence,
            source="model",
            intent_hint=intent_hint,
            resolution_state="not_applicable",
            turn_actions=turn_actions,
        )
    if confidence < 0.65:
        return context_clarification_resolution(
            question, history, "low_confidence",
            relation=relation, confidence=confidence, intent_hint=intent_hint,
        )
    recalled_messages: tuple[dict, ...] = ()
    if relation == "recall":
        recalled_messages = _recall_records(history, target_message_ids)
        valid_ids = {int(item["message_id"]) for item in recalled_messages}
        if not target_message_ids or not set(target_message_ids).issubset(valid_ids):
            return unresolved_context(question, "fallback", failure_reason="protocol_error")
        topic_anchor = " | ".join(
            _plain(str(item.get("content") or ""), 300)
            for item in recalled_messages
            if item.get("content")
        )[:1200]
    if not resolved or (relation == "recall" and not recalled_messages):
        return unresolved_context(question, "fallback", failure_reason="protocol_error")
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
        intent_hint=intent_hint,
        target_message_ids=target_message_ids if relation == "recall" else (),
        recalled_messages=recalled_messages,
        resolution_state="resolved",
        turn_actions=turn_actions,
    )


def context_system_message(resolution: ContextResolution) -> str:
    return (
        "当前输入依赖会话历史。context_resolution 是独立的语义上下文阶段产生的结构化结果，"
        "只用于恢复指代或用户修正，不是制造事实、证据或隐藏思维链。"
        "回答时完成 resolved_question，仍须通过正常工具和证据约束验证事实。\n"
        f"context_resolution={json.dumps(resolution.to_dict(), ensure_ascii=False, separators=(',', ':'))}"
    )
