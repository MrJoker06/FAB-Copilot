from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
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
    "fab_diagnostic",
    "fab_overview",
    "enterprise_data",
    "general_knowledge",
    "conversation",
    "ambiguous",
    "unknown",
]
RiskLevel = Literal["low", "medium", "high"]
ScopeType = Literal["fab", "process", "equipment", "product", "unknown", "not_applicable"]


INTENT_LABELS: dict[str, str] = {
    "capability_excursion": "制程能力异常",
    "yield_decline": "良率分析",
    "equipment_fault": "设备故障分析",
    "lot_trace": "批次追踪",
    "sop_lookup": "SOP 与知识查询",
    "defect_analysis": "缺陷分析",
    "fab_diagnostic": "制造综合诊断",
    "fab_overview": "工厂总览",
    "enterprise_data": "企业模拟数据查询",
    "general_knowledge": "通用知识问答",
    "conversation": "助手对话",
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
        ("oee", 3), ("维护", 2), ("pm", 2), ("设备风险", 4),
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
    "fab_diagnostic": (
        ("制造综合诊断", 8), ("生产综合诊断", 8), ("全厂诊断", 7),
        ("运营诊断", 7), ("fab diagnostic", 7),
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
    "fab_diagnostic": (
        "get_fab_overview",
        "get_yield_trend",
        "get_process_capability",
        "get_equipment_health",
        "get_equipment_productivity",
        "get_defect_pareto",
        "get_recent_excursions",
    ),
    "fab_overview": ("get_fab_overview", "get_yield_trend", "get_equipment_health"),
    "enterprise_data": (
        "get_enterprise_data_manifest",
        "get_enterprise_fab_summary",
        "query_enterprise_data",
    ),
    "general_knowledge": ("search_knowledge",),
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
_RELATIVE_RANGE_PATTERN = re.compile(
    r"(?:最近|近|过去)\s*(\d{1,3}|[一二三四五六七八九十两]{1,3})\s*(天|日|周|星期|个月|月)"
)
_CONJUNCTION_PATTERN = re.compile(r"(?:和|与|以及|同时|并且|、|\band\b)", re.IGNORECASE)
_GENERAL_QUESTION_PATTERN = re.compile(
    r"(?:什么是|是什么|为什么|为何|区别|差别|异同|优缺点|原理|概念|定义|含义|"
    r"作用|用途|介绍|解释|如何理解|对比|比较|科普|优势|劣势|特点|相较|相比|"
    r"应用场景|适用场景|哪个好)"
)
_CONTEXT_DEPENDENT_PATTERN = re.compile(
    r"^(?:最后|第.+(?:点|项)|(?:请)?(?:继续|接着|往下)|(?:为什么|怎么|为何)(?:还)?没有继续|"
    r"(?:不涉及|不需要|无需).{0,12}(?:具体工艺|具体制程|具体制造|生产数据|厂内数据|设备数据)|"
    r"(?:仅仅|只是|就只是|只|仅).{0,8}(?:用于)?科普|直接回答)"
)
_CONVERSATION_PATTERN = re.compile(
    r"^(?:你好|您好|嗨|hi|hello|你是谁|介绍(?:一下)?你自己|自我介绍(?:一下)?|"
    r"你能做什么|你可以做什么|你有哪些能力)[。！!？?]*$",
    re.IGNORECASE,
)
_FAB_SCOPE_PATTERN = re.compile(
    r"(?:制造数据|生产数据|制造运营|生产运营|工厂|fab|全厂|产线|生产线|站点|"
    r"生产情况|生产状况|制造现状|生产现状|制造表现|生产表现|整体生产)",
    re.IGNORECASE,
)
_DIAGNOSTIC_GOAL_PATTERN = re.compile(
    r"(?:改进|改善|优化|提升|建议|风险|瓶颈|薄弱|短板|健康检查|诊断|"
    r"优先级|优先顺序|改善空间|提升机会|问题点|异常点|怎么样|怎么看|"
    r"现状分析|表现评估|比较|对比|排序|排名|综合分析|总结)",
    re.IGNORECASE,
)
_MANUFACTURING_REVIEW_PATTERN = re.compile(
    r"(?:分析|查看|检查|评估|盘点|总结|概览|概况|情况|状况|表现|运行状态|运营状态)",
    re.IGNORECASE,
)
_PROCESS_OPERATION_PATTERN = re.compile(
    r"(?:机台|设备|生产|制造|运营|运行|数据|情况|状况|表现|现状|指标|异常|产出|效率)",
    re.IGNORECASE,
)
_SCOPE_NOUN_PATTERN = re.compile(
    r"(?:生产|制造|产线|生产线|机台|设备|制程|站点|运营|运行|良率|缺陷|能力|状况|情况|表现)",
    re.IGNORECASE,
)
_SCOPE_CODE_PATTERN = re.compile(r"(?<![a-z0-9_-])([a-z][a-z0-9_-]{1,31})(?![a-z0-9_-])", re.IGNORECASE)
_SCOPE_CODE_STOPWORDS = {
    "alarm", "cd", "cpk", "defect", "e10", "fab", "hold", "lot", "oee", "pareto",
    "pm", "semi", "sop", "wafer", "wip", "yield",
}
_KNOWN_PRODUCTS = ("Orion-A1", "Orion-A2", "Nova-P1", "Nova-P2", "Atlas-M1")
_CROSS_DOMAIN_GOAL_PATTERN = re.compile(
    r"(?:比较|对比|关联|综合|整体|一起|同时|排序|排名|优先级|优先顺序)",
    re.IGNORECASE,
)
_CAPABILITY_PORTFOLIO_PATTERN = re.compile(
    r"(?:(?:各|所有|全厂).{0,8}(?:站点|制程|设备|机台)|"
    r"(?:哪些|哪个|最差|最低).{0,8}(?:站点|制程|设备|机台)|"
    r"(?:站点|制程|设备|机台).{0,8}(?:排名|排序|对比|比较))"
)
_SPECIALIZED_SCOPE_PATTERNS: dict[str, re.Pattern] = {
    "capability_excursion": re.compile(r"(?:cpk|制程能力|过程能力|能力不足|超规|规格限)", re.IGNORECASE),
    "yield_decline": re.compile(r"(?:良率|yield|直通率|报废率)", re.IGNORECASE),
    "equipment_fault": re.compile(r"(?:设备风险|健康|故障|报警|alarm|宕机|停机|oee|稼动|维护|pm)", re.IGNORECASE),
    "lot_trace": re.compile(r"(?:批次|lot|晶圆|wafer|追踪|追溯|hold|wip)", re.IGNORECASE),
    "sop_lookup": re.compile(r"(?:sop|规范|作业指导|控制计划|知识库|文档|标准流程)", re.IGNORECASE),
    "defect_analysis": re.compile(r"(?:缺陷|defect|划伤|scratch|颗粒|particle|残留|wafer map|晶圆图|pareto)", re.IGNORECASE),
}


@dataclass(frozen=True)
class RoutedTimeRange:
    start: str
    end: str
    source: Literal["explicit", "relative", "today", "yesterday", "default_90_days"]
    assumed: bool


@dataclass(frozen=True)
class ManufacturingScopeResolution:
    scope_type: ScopeType
    resolved_ids: tuple[str, ...]
    unresolved_mentions: tuple[str, ...]
    source: Literal["deterministic"]
    confidence: float
    clarification_needed: bool


@dataclass(frozen=True)
class IntentRoute:
    intent: IntentName
    intent_label: str
    confidence: float
    candidate_intents: tuple[str, ...]
    process_steps: tuple[str, ...]
    equipment_ids: tuple[str, ...]
    scope_resolution: ManufacturingScopeResolution
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


def _looks_like_general_question(normalized: str) -> bool:
    return bool(
        not _CONTEXT_DEPENDENT_PATTERN.search(normalized)
        and _GENERAL_QUESTION_PATTERN.search(normalized)
    )


def _looks_like_conversation(normalized: str) -> bool:
    return bool(_CONVERSATION_PATTERN.fullmatch(normalized))


def _looks_like_fab_diagnostic(
    normalized: str,
    process_steps: tuple[str, ...],
    scores: dict[str, int],
) -> bool:
    explicit_diagnostic = bool(_DIAGNOSTIC_GOAL_PATTERN.search(normalized))
    scoped_review = bool(
        _MANUFACTURING_REVIEW_PATTERN.search(normalized)
        and (
            _FAB_SCOPE_PATTERN.search(normalized)
            or (process_steps and _PROCESS_OPERATION_PATTERN.search(normalized))
        )
    )
    if not explicit_diagnostic and not scoped_review:
        return False
    if not explicit_diagnostic and scores.get("fab_overview", 0) >= 4:
        return False
    specialized = tuple(
        intent for intent, pattern in _SPECIALIZED_SCOPE_PATTERNS.items()
        if pattern.search(normalized)
    )
    strong_specialized = tuple(intent for intent in specialized if scores.get(intent, 0) >= 4)
    if len(strong_specialized) >= 2:
        return True
    if len(specialized) >= 2 and _CROSS_DOMAIN_GOAL_PATTERN.search(normalized):
        return True
    if (
        strong_specialized == ("capability_excursion",)
        and not process_steps
        and _CAPABILITY_PORTFOLIO_PATTERN.search(normalized)
    ):
        return True
    if strong_specialized:
        return False
    if specialized and not (explicit_diagnostic and _FAB_SCOPE_PATTERN.search(normalized)):
        return False
    return bool(process_steps or _FAB_SCOPE_PATTERN.search(normalized))


def _process_steps(normalized: str, equipment_ids: tuple[str, ...]) -> tuple[str, ...]:
    found: set[str] = {equipment_id.split("-", 1)[0] for equipment_id in equipment_ids}
    for process_step, aliases in PROCESS_ALIASES.items():
        terms = (process_step.lower(), *aliases)
        if any(_contains(normalized, term.lower()) for term in terms):
            found.add(process_step)
    return tuple(step for step in MANUFACTURING_STEPS if step in found)


def _scope_code_mentions(
    normalized: str,
    process_steps: tuple[str, ...],
    equipment_ids: tuple[str, ...],
    products: tuple[str, ...],
) -> tuple[str, ...]:
    known = {
        *(step.lower() for step in process_steps),
        *(equipment_id.lower() for equipment_id in equipment_ids),
        *(product.lower() for product in products),
    }
    mentions: list[str] = []
    for match in _SCOPE_CODE_PATTERN.finditer(normalized):
        token = match.group(1)
        lowered = token.lower()
        if lowered in known or lowered in _SCOPE_CODE_STOPWORDS:
            continue
        context = normalized[max(0, match.start() - 12):min(len(normalized), match.end() + 12)]
        if not _SCOPE_NOUN_PATTERN.search(context):
            continue
        if token not in mentions:
            mentions.append(token.upper())
    return tuple(mentions)


def _manufacturing_scope_resolution(
    question: str,
    normalized: str,
    intent: str,
    process_steps: tuple[str, ...],
    equipment_ids: tuple[str, ...],
) -> ManufacturingScopeResolution:
    manufacturing_intents = {
        "capability_excursion", "yield_decline", "equipment_fault", "lot_trace",
        "defect_analysis", "fab_diagnostic", "fab_overview", "enterprise_data",
    }
    if intent not in manufacturing_intents:
        return ManufacturingScopeResolution("not_applicable", (), (), "deterministic", 1.0, False)
    if equipment_ids:
        return ManufacturingScopeResolution("equipment", equipment_ids, (), "deterministic", 1.0, False)
    if process_steps:
        return ManufacturingScopeResolution("process", process_steps, (), "deterministic", 1.0, False)

    products = tuple(product for product in _KNOWN_PRODUCTS if product.lower() in normalized)
    if products:
        return ManufacturingScopeResolution("product", products, (), "deterministic", 1.0, False)

    unresolved = _scope_code_mentions(normalized, process_steps, equipment_ids, products)
    if unresolved:
        return ManufacturingScopeResolution("unknown", (), unresolved, "deterministic", 0.99, True)
    if _FAB_SCOPE_PATTERN.search(normalized) or intent in {"fab_diagnostic", "fab_overview", "yield_decline"}:
        return ManufacturingScopeResolution("fab", ("FAB",), (), "deterministic", 0.9, False)
    return ManufacturingScopeResolution("not_applicable", (), (), "deterministic", 0.8, False)


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


def _range_amount(value: str) -> int:
    if value.isdigit():
        return max(1, int(value))
    digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if "十" not in value:
        return max(1, digits.get(value, 1))
    tens, _, ones = value.partition("十")
    return max(1, (digits.get(tens, 1) * 10) + digits.get(ones, 0))


def _time_range(question: str, current_date: date) -> RoutedTimeRange:
    explicit_dates = _parse_explicit_dates(question)
    if explicit_dates:
        start = min(explicit_dates)
        end = max(explicit_dates)
        return RoutedTimeRange(start.isoformat(), end.isoformat(), "explicit", False)

    match = _RELATIVE_RANGE_PATTERN.search(question)
    if match:
        amount = _range_amount(match.group(1))
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
    fab_diagnostic = _looks_like_fab_diagnostic(normalized, process_steps, scores)

    clarification_questions: list[str] = []
    if fab_diagnostic:
        intent = "fab_diagnostic"
        candidate_intents = ("fab_diagnostic",)
        confidence = 0.9
    elif not positive:
        if _looks_like_conversation(normalized):
            intent = "conversation"
            candidate_intents = ("conversation",)
            confidence = 0.95
        elif _looks_like_general_question(normalized):
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
