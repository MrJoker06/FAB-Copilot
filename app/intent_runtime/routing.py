from __future__ import annotations

from dataclasses import replace
from datetime import date

from .contracts import IntentRoute
from .rules import _CONJUNCTION_PATTERN, _DATA_REQUIREMENTS, _EQUIPMENT_PATTERN, _INTENT_PRIORITY, _contains, _intent_scores, _looks_like_conversation, _looks_like_fab_diagnostic, _looks_like_general_question, _risk, INTENT_LABELS
from .scope import _manufacturing_scope_resolution, _process_steps
from .time import _time_range

def route_question(question: str, current_date: date | None = None) -> IntentRoute:
    normalized = " ".join(question.lower().split())
    equipment_ids = tuple(dict.fromkeys(match.group(0).upper() for match in _EQUIPMENT_PATTERN.finditer(question)))
    process_steps = _process_steps(normalized, equipment_ids)
    scores = _intent_scores(normalized)
    ranked = sorted(scores, key=lambda name: (-scores[name], _INTENT_PRIORITY.index(name)))
    positive = [name for name in ranked if scores[name] > 0]
    fab_diagnostic = _looks_like_fab_diagnostic(normalized, process_steps, scores)

    clarification_questions: list[str] = []
    if _looks_like_conversation(normalized):
        intent = "conversation"
        candidate_intents = ("conversation",)
        confidence = 0.95
    elif fab_diagnostic:
        intent = "fab_diagnostic"
        candidate_intents = ("fab_diagnostic",)
        confidence = 0.9
    elif not positive:
        if _looks_like_general_question(normalized):
            intent = "general_knowledge"
            candidate_intents = ("general_knowledge",)
            confidence = 0.8
        else:
            intent = "unknown"
            candidate_intents = ()
            confidence = 0.0
            clarification_questions.append("请说明要分析的指标或目标，例如 Cpk、良率、设备故障、批次追踪或 SOP。")
    else:
        top, second = positive[0], positive[1] if len(positive) > 1 else None
        close_multi_intent = bool(
            second
            and scores[top] - scores[second] <= 1
            and _CONJUNCTION_PATTERN.search(normalized)
        )
        if close_multi_intent:
            intent = "ambiguous"
            candidate_intents = tuple(positive[:3])
            confidence = 0.45
            clarification_questions.append(
                "问题同时包含多个分析目标，请确认优先分析哪一项："
                + "、".join(INTENT_LABELS[name] for name in candidate_intents)
                + "。"
            )
        else:
            intent = top  # type: ignore[assignment]
            candidate_intents = tuple(positive[:3])
            score_total = sum(scores[name] for name in positive)
            confidence = round(min(0.99, 0.55 + 0.44 * scores[top] / max(1, score_total)), 2)

    if intent == "capability_excursion" and not process_steps:
        clarification_questions.append("请指定需要计算制程能力的站点，例如 CMP、光刻或刻蚀。")

    scope_resolution = _manufacturing_scope_resolution(
        question,
        normalized,
        intent,
        process_steps,
        equipment_ids,
    )
    if scope_resolution.clarification_needed:
        mentions = "、".join(f"“{item}”" for item in scope_resolution.unresolved_mentions)
        clarification_questions.append(
            f"未能将{mentions}映射到现有制程、产品或设备组。请确认它代表什么，或明确是否需要整厂分析。"
        )

    requirements: list[str] = []
    requirement_intents = candidate_intents if intent == "ambiguous" else (intent,)
    for candidate in requirement_intents:
        for requirement in _DATA_REQUIREMENTS.get(candidate, ()):
            if requirement not in requirements:
                requirements.append(requirement)

    risk_level, risk_reasons = _risk(normalized, intent)
    if scope_resolution.clarification_needed:
        risk_level = "medium"
        risk_reasons = ("制造分析范围尚未确认",)
    return IntentRoute(
        intent=intent,
        intent_label=INTENT_LABELS[intent],
        confidence=confidence,
        candidate_intents=candidate_intents,
        process_steps=process_steps,
        equipment_ids=equipment_ids,
        scope_resolution=scope_resolution,
        time_range=_time_range(question, current_date or date.today()),
        data_requirements=tuple(requirements),
        risk_level=risk_level,
        risk_reasons=risk_reasons,
        clarification_needed=bool(clarification_questions),
        clarification_questions=tuple(clarification_questions),
    )


def apply_semantic_intent_hint(
    route: IntentRoute,
    intent_hint: str,
    confidence: float,
    *,
    context_applied: bool = False,
) -> IntentRoute:
    """Use a high-confidence semantic hint without overriding manufacturing routes."""
    if route.intent == "unknown" and intent_hint == "conversation" and confidence >= 0.65:
        return replace(
            route,
            intent="conversation",
            intent_label=INTENT_LABELS["conversation"],
            confidence=round(min(confidence, 0.95), 2),
            candidate_intents=("conversation",),
            data_requirements=(),
            risk_level="low",
            risk_reasons=(),
            clarification_needed=False,
            clarification_questions=(),
        )
    eligible_intents = {"unknown"}
    if context_applied:
        eligible_intents.add("sop_lookup")
    if route.intent not in eligible_intents or intent_hint != "general_knowledge" or confidence < 0.65:
        return route
    return replace(
        route,
        intent="general_knowledge",
        intent_label=INTENT_LABELS["general_knowledge"],
        confidence=round(min(confidence, 0.85), 2),
        candidate_intents=("general_knowledge",),
        data_requirements=_DATA_REQUIREMENTS["general_knowledge"],
        risk_level="low",
        risk_reasons=(),
        clarification_needed=False,
        clarification_questions=(),
    )


def routing_system_message(route: IntentRoute) -> str:
    return (
        "以下是确定性 Intent Router 生成的结构化分析上下文，不是制造事实或证据。"
        "intent=general_knowledge 时必须先检索当前用户个人知识和工厂知识，再由检索决策决定是否允许模型补充；"
        "intent=conversation 时由服务端直接回答助手身份与能力，不检索知识库或制造数据；"
        "仅 intent=general_knowledge 或 conversation 时不得调用制造数据工具。"
        "其他制造意图应优先使用 data_requirements 中的工具收集证据，并将 process_steps、equipment_ids 和 time_range 作为参数范围。"
        "通用问题若术语含糊，只澄清术语本身，不得索要制程、设备、批次或时间范围。"
        "若 clarification_needed=true，应先澄清关键歧义，避免无范围的广泛查询。"
        "risk_level=high 时只能提供待复核建议，不得直接要求执行高风险动作。\n"
        f"intent_route={route.to_prompt()}"
    )
