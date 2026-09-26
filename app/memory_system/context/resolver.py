"""Pure deterministic and semantic contextual-memory resolution."""
from __future__ import annotations

import re

from ..contracts import (
    ContextRelation,
    ContextResolution,
    IntentHint,
    ResolutionSource,
    ResolutionState,
    ResolutionStrategy,
)
from .history import (
    _history_index,
    _number,
    _options,
    _plain,
    _previous_user_question,
    _recall_records,
)


_ORDINAL_PATTERN = re.compile(
    r"^(?:选择|选|就)?\s*第\s*([一二三四五六七八九十两\d]+)\s*(?:点|项|个)\s*(?:吧|即可)?[。！!？?]*$"
)
_LAST_PATTERN = re.compile(
    r"^(?:选择|选|就)?\s*(?:最后|末尾)(?:一)?(?:点|项|个)\s*(?:吧|即可)?[。！!？?]*$"
)


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
