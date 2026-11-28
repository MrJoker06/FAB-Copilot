"""Versioned playbooks that consume only named manufacturing query tools."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from typing import Protocol

from ..intent_runtime.contracts import IntentRoute
from app.planning_runtime.builtin_playbooks import DOMAIN_PLAYBOOKS
from app.planning_runtime.playbook_contracts import DomainPlaybook
from app.skills.policies.manufacturing import named_requirements as _requirements
from app.planning_runtime.playbook_contracts import PlaybookReference
from app.planning_runtime.playbook_contracts import PlaybookSelection


class _Route(Protocol):
    intent: str
    candidate_intents: tuple[str, ...]


NAMED_QUERY_CAPABILITY_ID = "manufacturing-named-queries"
NAMED_QUERY_CAPABILITY_VERSION = "2.0.0"
NAMED_PLAYBOOK_VERSION = "2.0.0"
NAMED_PLAYBOOK_RELEASED_AT = "2026-10-31"







NAMED_DOMAIN_PLAYBOOKS: dict[str, DomainPlaybook] = {
    intent: replace(
        playbook,
        schema_version="2.0",
        playbook_version=NAMED_PLAYBOOK_VERSION,
        released_at=NAMED_PLAYBOOK_RELEASED_AT,
        evidence_requirements=_requirements(playbook),
    )
    for intent, playbook in DOMAIN_PLAYBOOKS.items()
}


def _reference(playbook: DomainPlaybook) -> PlaybookReference:
    return PlaybookReference(
        playbook_id=playbook.playbook_id,
        playbook_version=playbook.playbook_version,
        intent=playbook.intent,
        title=playbook.title,
    )


def select_named_playbook(route: _Route) -> PlaybookSelection:
    selected = NAMED_DOMAIN_PLAYBOOKS.get(route.intent)
    if selected is not None:
        return PlaybookSelection(
            status="selected",
            route_intent=route.intent,
            selected_playbook=selected,
            candidate_playbooks=(_reference(selected),),
            reason="路由意图与具名查询 Domain Playbook 精确匹配。",
        )
    if route.intent == "ambiguous":
        candidates = tuple(
            _reference(NAMED_DOMAIN_PLAYBOOKS[intent])
            for intent in route.candidate_intents
            if intent in NAMED_DOMAIN_PLAYBOOKS
        )
        if candidates:
            return PlaybookSelection(
                status="clarification_required",
                route_intent=route.intent,
                selected_playbook=None,
                candidate_playbooks=candidates,
                reason="多个具名查询 Domain Playbook 同时匹配；澄清主目标前不执行任一模板。",
            )
    return PlaybookSelection(
        status="unsupported",
        route_intent=route.intent,
        selected_playbook=None,
        candidate_playbooks=(),
        reason="当前六类具名查询 Domain Playbook 不覆盖该意图，继续使用通用 Agent 规则。",
    )


def focus_duty_lookup(question: str, route: IntentRoute, selection: PlaybookSelection) -> PlaybookSelection:
    selected = selection.selected_playbook
    if (
        selected is None or selected.playbook_version != NAMED_PLAYBOOK_VERSION
        or route.request_type != "data_query" or len(route.equipment_ids) != 1
        or re.search(
            r"温度|温漂|传感器|规格|对比|比较|阈值|达标|合格|超标|高于|低于|"
            r"均值|方差|标准差|样本|恢复|根因|原因|[、；;]",
            question,
        )
    ):
        return selection
    if route.intent == "capability_excursion" and re.search(r"\bcpk\b", question, re.I):
        plan_id, evidence_id, tool, fields, title = (
            "PB-DUTY-CPK", "CAP-01", "get_process_capability",
            ("equipment_id", "metric_name", "cpk"), "制程能力 Cpk",
        )
    elif route.intent == "equipment_fault" and re.search(r"报警|\balarm\b", question, re.I):
        plan_id, evidence_id, tool, fields, title = (
            "PB-DUTY-ALARMS", "EQP-03", "get_equipment_event_timeline",
            ("equipment_id", "event_time", "event_type"), "设备报警",
        )
    else:
        return selection
    requirement = next(item for item in selected.evidence_requirements if item.evidence_id == evidence_id)
    focused = replace(
        selected, playbook_id=plan_id, title=title,
        objective=f"查询目标机台和日期范围内的{title}。",
        evidence_requirements=(replace(
            requirement, name=title, source_tools=(tool,), required_fields=fields,
            acceptance_criteria=("核对机台、日期和实际结果。",),
        ),),
        analysis_questions=(),
    )
    return replace(selection, selected_playbook=focused, candidate_playbooks=(_reference(focused),))


_DUTY_DATE_REPLY = re.compile(
    r"(?:(?:确认(?:改查)?|改查|查|就查)\s*)?(20\d{2}-\d{2}-\d{2})\s*全天(?:记录|数据)?[。！!]*"
)


def resolve_duty_date_reply(question: str, history: list[dict]) -> str | None:
    """Resume only an immediately preceding day-grain clarification."""
    matched = _DUTY_DATE_REPLY.fullmatch(question.strip())
    if not matched or not history or history[-1].get("role") != "assistant":
        return None
    try:
        day = date.fromisoformat(matched[1])
    except ValueError:
        return None
    metadata = history[-1].get("metadata")
    if not isinstance(metadata, dict):
        return None
    plan = metadata.get("execution_plan")
    if (
        not isinstance(plan, dict)
        or plan.get("status") != "clarification_required"
        or plan.get("missing_inputs") != ["supported_time_range"]
    ):
        return None
    route, contract = metadata.get("intent_route"), metadata.get("answer_contract")
    if not isinstance(route, dict) or not isinstance(contract, dict):
        return None
    equipment = route.get("equipment_ids")
    policy = contract.get("evidence_policy_ref")
    if (
        not isinstance(equipment, list)
        or len(equipment) != 1
        or not isinstance(equipment[0], str)
        or not re.fullmatch(r"[A-Z]+-[0-9]{1,3}[A-Z]?", equipment[0])
        or not isinstance(policy, dict)
    ):
        return None
    if (route.get("intent"), policy.get("component_id")) == ("equipment_fault", "PB-DUTY-ALARMS"):
        return f"查询 {day} {equipment[0]} 报警次数"
    if (route.get("intent"), policy.get("component_id")) == ("capability_excursion", "PB-DUTY-CPK"):
        return f"查询 {day} {equipment[0]} 的 Cpk 是多少"
    return None


__all__ = [
    "NAMED_DOMAIN_PLAYBOOKS",
    "NAMED_PLAYBOOK_RELEASED_AT",
    "NAMED_PLAYBOOK_VERSION",
    "NAMED_QUERY_CAPABILITY_ID",
    "NAMED_QUERY_CAPABILITY_VERSION",
    "resolve_duty_date_reply",
    "select_named_playbook",
]
