from __future__ import annotations

from app.intent_runtime.contracts import IntentRoute
from .playbook_contracts import DomainPlaybook, PlaybookReference, PlaybookSelection
from .builtin_playbooks import DOMAIN_PLAYBOOKS


def _reference(playbook: DomainPlaybook) -> PlaybookReference:
    return PlaybookReference(
        playbook_id=playbook.playbook_id,
        playbook_version=playbook.playbook_version,
        intent=playbook.intent,
        title=playbook.title,
    )


def select_playbook(route: IntentRoute) -> PlaybookSelection:
    selected = DOMAIN_PLAYBOOKS.get(route.intent)
    if selected is not None:
        return PlaybookSelection(
            status="selected",
            route_intent=route.intent,
            selected_playbook=selected,
            candidate_playbooks=(_reference(selected),),
            reason="路由意图与版本化 Domain Playbook 精确匹配。",
        )

    if route.intent == "ambiguous":
        candidates = tuple(
            _reference(DOMAIN_PLAYBOOKS[intent])
            for intent in route.candidate_intents
            if intent in DOMAIN_PLAYBOOKS
        )
        if candidates:
            return PlaybookSelection(
                status="clarification_required",
                route_intent=route.intent,
                selected_playbook=None,
                candidate_playbooks=candidates,
                reason="多个 Domain Playbook 同时匹配；澄清主目标前不执行任一模板。",
            )

    return PlaybookSelection(
        status="unsupported",
        route_intent=route.intent,
        selected_playbook=None,
        candidate_playbooks=(),
        reason="当前六类 Domain Playbook 不覆盖该意图，继续使用通用 Agent 规则。",
    )


def playbook_system_message(selection: PlaybookSelection) -> str:
    return (
        "以下是 Domain Playbook 选择结果。Playbook 是取证与回答契约，不是执行结果，也不证明任何制造事实。"
        "status=selected 时，在形成结论前覆盖全部 required=true 的证据；无法取得时必须列出缺口。"
        "status=clarification_required 时先澄清，不得混合执行候选模板。"
        "不得绕过 safety_constraints，历史案例不得替代当前数据或正式规范。\n"
        f"domain_playbook={selection.to_prompt()}"
    )
