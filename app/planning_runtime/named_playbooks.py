"""Versioned playbooks that consume only named manufacturing query tools."""

from __future__ import annotations

import re
from dataclasses import replace
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


__all__ = [
    "NAMED_DOMAIN_PLAYBOOKS",
    "NAMED_PLAYBOOK_RELEASED_AT",
    "NAMED_PLAYBOOK_VERSION",
    "NAMED_QUERY_CAPABILITY_ID",
    "NAMED_QUERY_CAPABILITY_VERSION",
    "select_named_playbook",
]
