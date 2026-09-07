"""Model-message and general-knowledge preparation stage."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..coordinator_state import CoordinatorRunState

if TYPE_CHECKING:
    from ..dependencies import CoordinatorDependencies


async def prepare_model_stage(
    state: CoordinatorRunState, *, deps: "CoordinatorDependencies",
) -> CoordinatorRunState:
    deps.emit_evidence_validation(state.run_id, 0, state.evidence_validation.to_dict())
    state.messages = [{"role": "system", "content": deps.system_prompt}]
    if state.context_resolution.applied:
        state.messages.append({
            "role": "system",
            "content": deps.context_system_message(state.context_resolution),
        })
    state.messages.extend([
        {"role": "system", "content": deps.routing_system_message(state.intent_route)},
        {"role": "system", "content": deps.playbook_system_message(state.playbook_selection)},
        {"role": "system", "content": deps.planner_system_message(state.execution_plan)},
        {"role": "system", "content": deps.validator_system_message(state.evidence_validation)},
        {"role": "system", "content": deps.synthesizer_system_message(state.answer_contract)},
    ])
    for item in (state.history or [])[-8:]:
        role = item.get("role")
        content = str(item.get("content", ""))[:4000]
        if role in {"user", "assistant"} and content:
            state.messages.append({"role": role, "content": content})
    state.messages.append({"role": "user", "content": state.question})
    state.endpoint = f"{state.connection.base_url}/chat/completions"
    state.total_usage = {
        key: int(state.context_usage.get(key, 0) or 0)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    state.health = state.model_health
    state.knowledge_fallback = {"used": False, "reason": None, "disclosure": None}
    state.retrieval_decision_payload = {
        "state": "NOT_APPLICABLE", "reason": None, "attempted_scopes": [], "attempts": [],
        "selected_reference_ids": [], "source_counts": {"personal": 0, "knowledge": 0, "case": 0},
        "rewritten_query": None, "assumptions": [], "model_knowledge_allowed": False, "disclosure": None,
    }
    if state.intent_route.intent == "general_knowledge":
        decision = await deps.prefetch_general_knowledge(
            state.analysis_question, state.run_id, state.loop_guard, state.evidence_observations,
            state.trace, state.sources, state.progress,
        )
        state.retrieval_decision_payload = decision.to_dict()
        state.knowledge_fallback = {
            "used": decision.model_knowledge_allowed,
            "reason": decision.reason if decision.model_knowledge_allowed else None,
            "disclosure": decision.disclosure,
        }
        state.evidence_validation = deps.validate_evidence(
            state.execution_plan, state.selected_playbook, state.evidence_observations,
        )
        state.answer_contract = deps.create_answer_contract(
            state.evidence_validation, list(state.sources.values()),
            allow_model_knowledge_fallback=decision.model_knowledge_allowed,
        )
        state.messages.extend([
            {"role": "system", "content": deps.retrieval_system_message(decision, list(state.sources.values()))},
            {"role": "system", "content": deps.synthesizer_system_message(state.answer_contract)},
            {"role": "system", "content": (
                "当前是知识型问题的最终回答阶段。只输出面向用户的中文 Markdown 正文；"
                "不得输出 JSON、tool_calls、函数参数或 submit_analysis，且不得请求生产范围。"
            )},
        ])
        if state.knowledge_fallback["used"]:
            state.fallback_announced = True
            deps.emit(
                "knowledge_fallback_enabled", state.run_id,
                reason=state.knowledge_fallback["reason"], model=state.connection.model,
                retrieval_state=decision.state,
            )
            await deps.notify(state.progress, {
                "event": "stage", "stage": "knowledge_fallback",
                "message": (
                    "知识库仅覆盖部分内容，正在使用模型通用知识补充"
                    if decision.state == "HYBRID_GENERAL_SUPPLEMENT"
                    else "个人知识库和工厂知识库均未检索到可用内容，正在使用模型通用知识回答"
                ),
                "knowledge_fallback": state.knowledge_fallback,
            })
    return state


def build_result(state: CoordinatorRunState, deps: "CoordinatorDependencies", answer: str, report: Any) -> dict:
    return deps.build_result(
        answer, report, trace=state.trace, sources=state.sources, intent_route=state.intent_route,
        connection=state.connection, total_usage=state.total_usage, route_payload=state.route_payload,
        playbook_payload=state.playbook_payload, plan_payload=state.plan_payload,
        loop_guard=state.loop_guard, evidence_validation=state.evidence_validation,
        answer_contract=state.answer_contract, context_resolution=state.context_resolution,
        knowledge_fallback=state.knowledge_fallback,
        retrieval_decision_payload=state.retrieval_decision_payload, thinking=state.thinking,
        thinking_answer_effective=state.thinking_answer_effective, turn_decision=state.turn_decision,
    )
