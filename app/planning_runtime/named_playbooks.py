"""Versioned playbooks that consume only named manufacturing query tools."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

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


__all__ = [
    "NAMED_DOMAIN_PLAYBOOKS",
    "NAMED_PLAYBOOK_RELEASED_AT",
    "NAMED_PLAYBOOK_VERSION",
    "NAMED_QUERY_CAPABILITY_ID",
    "NAMED_QUERY_CAPABILITY_VERSION",
    "select_named_playbook",
]
