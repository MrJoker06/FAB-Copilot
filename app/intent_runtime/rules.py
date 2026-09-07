from __future__ import annotations

import re

from ..processes import MANUFACTURING_STEPS
from .contracts import RiskLevel

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
    r"你能做什么|你可以做什么|你有什么功能|你有哪些能力)[。！!？?]*$",
    re.IGNORECASE,
)
# This asks whether the assistant can perform an action, rather than asking it
# to perform the action.  It intentionally does not enumerate manufacturing
# nouns, so "那就查昨天良率" remains a normal manufacturing request.
_ASSISTANT_ABILITY_QUESTION_PATTERN = re.compile(r"^你(?:能|可以|会).+(?:吗|么)[。！!？?]*$", re.IGNORECASE)
_META_RUNTIME_PATTERN = re.compile(r"^你现在.*(?:thinking|思考).*(?:吗|么)[。！!？?]*$", re.IGNORECASE)
_META_REVIEW_PATTERN = re.compile(r"^为什么刚才.*(?:答错|异常).*[？?吗么]?[。！!？?]*$", re.IGNORECASE)
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
    ability = _ASSISTANT_ABILITY_QUESTION_PATTERN.fullmatch(normalized) and not re.search(r"(?:帮我|为我|替我)", normalized)
    return bool(_CONVERSATION_PATTERN.fullmatch(normalized) or ability or _META_RUNTIME_PATTERN.fullmatch(normalized) or _META_REVIEW_PATTERN.fullmatch(normalized))


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
