from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Literal

from .processes import MANUFACTURING_STEPS, PROCESS_ALIASES


IntentName = Literal[
    "capability_excursion",
    "yield_decline",
    "equipment_fault",
    "lot_trace",
    "sop_lookup",
    "defect_analysis",
    "fab_overview",
    "enterprise_data",
    "ambiguous",
    "unknown",
]
RiskLevel = Literal["low", "medium", "high"]


INTENT_LABELS: dict[str, str] = {
    "capability_excursion": "制程能力异常",
    "yield_decline": "良率分析",
    "equipment_fault": "设备故障分析",
    "lot_trace": "批次追踪",
    "sop_lookup": "SOP 与知识查询",
    "defect_analysis": "缺陷分析",
    "fab_overview": "工厂总览",
    "enterprise_data": "企业模拟数据查询",
    "ambiguous": "多意图问题",
    "unknown": "未知意图",
}

_INTENT_RULES: dict[str, tuple[tuple[str, int], ...]] = {
    "capability_excursion": (
        ("cpk", 5), ("制程能力", 5), ("过程能力", 5), ("能力不足", 4),
        ("不合格", 3), ("超规", 3), ("超出规格", 3), ("漂移", 2),
    ),
    "yield_decline": (
        ("良率", 5), ("yield", 5), ("直通率", 4), ("报废率", 3),
        ("产品组合", 2), ("趋势", 1),
    ),
    "equipment_fault": (
        ("设备", 2), ("故障", 4), ("报警", 3), ("alarm", 3),
        ("宕机", 4), ("停机", 3), ("健康", 3), ("稼动", 3),
        ("oee", 3), ("维护", 2), ("pm", 2),
    ),
    "lot_trace": (
        ("批次", 4), ("lot", 4), ("晶圆", 2), ("wafer", 2),
        ("追踪", 4), ("追溯", 4), ("履历", 4), ("hold", 3),
        ("在制", 3), ("wip", 3), ("流转", 3),
    ),
    "sop_lookup": (
        ("sop", 6), ("规范", 4), ("作业指导", 5), ("控制计划", 5),
        ("知识库", 4), ("文档", 3), ("标准流程", 4), ("处置流程", 4),
        ("怎么处理", 4), ("如何处置", 4),
    ),
    "defect_analysis": (
        ("缺陷", 4), ("defect", 4), ("划伤", 4), ("scratch", 4),
        ("颗粒", 3), ("particle", 3), ("cd shift", 4), ("残留", 3),
        ("倒塌", 3), ("wafer map", 4), ("晶圆图", 4), ("pareto", 3),
    ),
    "fab_overview": (
        ("工厂总览", 6), ("fab 总览", 6), ("整体概况", 5),
        ("生产概况", 4), ("全厂", 3),
    ),
    "enterprise_data": (
        ("企业模拟数据", 7), ("数据接口", 5), ("亿级", 5),
        ("数据规模", 4), ("投影分析", 5), ("enterprise", 4),
    ),
}

_DATA_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "capability_excursion": (
        "get_process_capability",
        "get_recent_excursions",
        "get_sensor_summary",
        "search_knowledge",
    ),
    "yield_decline": (
        "get_yield_trend",
        "get_fab_overview",
        "get_defect_pareto",
        "search_knowledge",
    ),
    "equipment_fault": (
        "get_equipment_health",
        "get_equipment_productivity",
        "get_recent_excursions",
        "get_sensor_summary",
        "search_knowledge",
    ),
    "lot_trace": ("query_manufacturing_data", "search_knowledge"),
    "sop_lookup": ("search_knowledge",),
    "defect_analysis": (
        "get_defect_pareto",
        "get_recent_excursions",
        "query_manufacturing_data",
        "search_knowledge",
    ),
    "fab_overview": ("get_fab_overview", "get_yield_trend", "get_equipment_health"),
    "enterprise_data": (
        "get_enterprise_data_manifest",
        "get_enterprise_fab_summary",
        "query_enterprise_data",
    ),
}

_INTENT_PRIORITY = tuple(_INTENT_RULES)
_EQUIPMENT_PATTERN = re.compile(
    rf"\b(?:{'|'.join(MANUFACTURING_STEPS)})-[0-9]{{1,3}}[A-Z]?\b",
    re.IGNORECASE,
)
_LOT_PATTERN = re.compile(
    r"\b(?:LOT[-_ ]?[A-Z0-9]+(?:-[A-Z0-9]+)*|L\d{4,}-\d{3,})\b",
    re.IGNORECASE,
)
_EXPLICIT_DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?!\d)")
_RELATIVE_RANGE_PATTERN = re.compile(r"(?:最近|近|过去)\s*(\d{1,3})\s*(天|日|周|星期|个月|月)")
_CONJUNCTION_PATTERN = re.compile(r"(?:和|与|以及|同时|并且|、|\band\b)", re.IGNORECASE)


@dataclass(frozen=True)
class RoutedTimeRange:
    start: str
    end: str
    source: Literal["explicit", "relative", "today", "yesterday", "default_90_days"]
    assumed: bool


@dataclass(frozen=True)
class IntentRoute:
    intent: IntentName
    intent_label: str
    confidence: float
    candidate_intents: tuple[str, ...]
    process_steps: tuple[str, ...]
    equipment_ids: tuple[str, ...]
    time_range: RoutedTimeRange
    data_requirements: tuple[str, ...]
    risk_level: RiskLevel
    risk_reasons: tuple[str, ...]
    clarification_needed: bool
    clarification_questions: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_prompt(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def _contains(text: str, keyword: str) -> bool:
    if keyword.isascii() and keyword.replace(" ", "").isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None
    return keyword in text


def _intent_scores(normalized: str) -> dict[str, int]:
    scores = {
        intent: sum(weight for keyword, weight in rules if _contains(normalized, keyword))
        for intent, rules in _INTENT_RULES.items()
    }
    if _LOT_PATTERN.search(normalized):
        scores["lot_trace"] += 5
    return scores


def _process_steps(normalized: str, equipment_ids: tuple[str, ...]) -> tuple[str, ...]:
    found: set[str] = {equipment_id.split("-", 1)[0] for equipment_id in equipment_ids}
    for process_step, aliases in PROCESS_ALIASES.items():
        terms = (process_step.lower(), *aliases)
        if any(_contains(normalized, term.lower()) for term in terms):
            found.add(process_step)
    return tuple(step for step in MANUFACTURING_STEPS if step in found)


def _parse_explicit_dates(question: str) -> tuple[date, ...]:
    parsed: list[date] = []
    for match in _EXPLICIT_DATE_PATTERN.finditer(question):
        try:
            value = date(*(int(part) for part in match.groups()))
        except ValueError:
            continue
        if value not in parsed:
            parsed.append(value)
    return tuple(parsed)


def _time_range(question: str, current_date: date) -> RoutedTimeRange:
    explicit_dates = _parse_explicit_dates(question)
    if explicit_dates:
        start = min(explicit_dates)
        end = max(explicit_dates)
        return RoutedTimeRange(start.isoformat(), end.isoformat(), "explicit", False)

    match = _RELATIVE_RANGE_PATTERN.search(question)
    if match:
        amount = max(1, int(match.group(1)))
        unit = match.group(2)
        days = amount if unit in {"天", "日"} else amount * (7 if unit in {"周", "星期"} else 30)
        start = current_date - timedelta(days=days - 1)
        return RoutedTimeRange(start.isoformat(), current_date.isoformat(), "relative", False)
    if "昨天" in question:
        yesterday = current_date - timedelta(days=1)
        return RoutedTimeRange(yesterday.isoformat(), yesterday.isoformat(), "yesterday", False)
    if "今天" in question or "今日" in question:
        return RoutedTimeRange(current_date.isoformat(), current_date.isoformat(), "today", False)
    start = current_date - timedelta(days=89)
    return RoutedTimeRange(start.isoformat(), current_date.isoformat(), "default_90_days", True)


def _risk(normalized: str, intent: str) -> tuple[RiskLevel, tuple[str, ...]]:
    high_signals = {
        "高风险处置": ("停机", "报废", "放行", "返工", "恢复量产", "冻结批次", "隔离批次", "修改配方", "配方变更"),
        "严重生产影响": ("全不合格", "全线异常", "良率暴跌", "安全联锁", "污染扩散"),
    }
    medium_signals = ("异常", "故障", "漂移", "下降", "不合格", "超规", "报警", "缺陷", "hold")
    reasons = tuple(label for label, terms in high_signals.items() if any(term in normalized for term in terms))
    if reasons:
        return "high", reasons
    if intent in {"ambiguous", "unknown"}:
        return "medium", ("意图或范围尚未确认",)
    if any(term in normalized for term in medium_signals):
        return "medium", ("问题包含制造异常信号",)
    return "low", ()


def route_question(question: str, current_date: date | None = None) -> IntentRoute:
    normalized = " ".join(question.lower().split())
    equipment_ids = tuple(dict.fromkeys(match.group(0).upper() for match in _EQUIPMENT_PATTERN.finditer(question)))
    process_steps = _process_steps(normalized, equipment_ids)
    scores = _intent_scores(normalized)
    ranked = sorted(scores, key=lambda name: (-scores[name], _INTENT_PRIORITY.index(name)))
    positive = [name for name in ranked if scores[name] > 0]

    clarification_questions: list[str] = []
    if not positive:
        intent: IntentName = "unknown"
        candidate_intents: tuple[str, ...] = ()
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

    requirements: list[str] = []
    requirement_intents = candidate_intents if intent == "ambiguous" else (intent,)
    for candidate in requirement_intents:
        for requirement in _DATA_REQUIREMENTS.get(candidate, ()):
            if requirement not in requirements:
                requirements.append(requirement)

    risk_level, risk_reasons = _risk(normalized, intent)
    return IntentRoute(
        intent=intent,
        intent_label=INTENT_LABELS[intent],
        confidence=confidence,
        candidate_intents=candidate_intents,
        process_steps=process_steps,
        equipment_ids=equipment_ids,
        time_range=_time_range(question, current_date or date.today()),
        data_requirements=tuple(requirements),
        risk_level=risk_level,
        risk_reasons=risk_reasons,
        clarification_needed=bool(clarification_questions),
        clarification_questions=tuple(clarification_questions),
    )


def routing_system_message(route: IntentRoute) -> str:
    return (
        "以下是确定性 Intent Router 生成的结构化分析上下文，不是制造事实或证据。"
        "优先使用 data_requirements 中的工具收集证据，并将 process_steps、equipment_ids 和 time_range 作为参数范围。"
        "若 clarification_needed=true，应先澄清关键歧义，避免无范围的广泛查询。"
        "risk_level=high 时只能提供待复核建议，不得直接要求执行高风险动作。\n"
        f"intent_route={route.to_prompt()}"
    )
