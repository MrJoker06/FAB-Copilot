"""Model availability and deterministic fallback stage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..coordinator_state import CoordinatorRunState

if TYPE_CHECKING:
    from ..dependencies import CoordinatorDependencies


@dataclass(frozen=True)
class AvailabilityOutcome:
    state: CoordinatorRunState
    result: dict | None = None


async def handle_model_availability(
    state: CoordinatorRunState, *, deps: "CoordinatorDependencies",
) -> AvailabilityOutcome:
    state.connection = state.settings.model_connection
    state.model_health = (
        deps.get_model_health(state.selected_model_id)
        if state.health_enabled else {"status": "unknown"}
    )
    health_allowed = True
    if state.connection.api_key and state.health_enabled:
        health_allowed, state.model_health, transition = deps.claim_model_call(
            state.selected_model_id,
            cooldown_seconds=state.settings.model_circuit_cooldown_seconds,
            lease_seconds=state.settings.model_circuit_recovery_lease_seconds,
        )
        if transition:
            state.main_recovery_trial = transition in {"recovery_started", "recovery_reclaimed"}
            deps.emit(
                "model_circuit_recovery_started", state.run_id,
                model_id=state.selected_model_id, health=state.model_health,
            )
    if state.connection.api_key and health_allowed:
        return AvailabilityOutcome(state)
    await deps.notify(state.progress, {
        "event": "stage", "stage": "planning", "message": "正在使用本地规则规划分析路径",
    })
    reason = "missing_api_key" if not state.connection.api_key else "circuit_open"
    if reason == "circuit_open":
        deps.emit(
            "model_local_fallback_activated", state.run_id,
            model_id=state.selected_model_id, reason=reason, health=state.model_health,
        )
    if state.execution_plan.status == "ready":
        return AvailabilityOutcome(state, await _ready_fallback(state, deps, reason))
    result = deps.offline_answer(
        state.analysis_question, state.intent_route, state.playbook_selection,
        state.execution_plan, state.loop_guard, fallback_reason=reason,
    )
    deps.emit_evidence_validation(state.run_id, 1, result["evidence_validation"])
    deps.emit(
        "answer_synthesis_completed", state.run_id,
        plan_id=result["answer_synthesis"]["plan_id"], status=result["answer_synthesis"]["status"],
        allowed_conclusion_strength=result["answer_synthesis"]["allowed_conclusion_strength"],
        source_count=len(result["answer_synthesis"]["source_refs"]),
        invalid_source_count=len(result["answer_synthesis"]["invalid_source_refs"]),
        moved_claims=result["answer_synthesis"]["moved_claims"],
        wording_adjustment_count=len(result["answer_synthesis"]["wording_adjustments"]),
    )
    for item in result["tool_trace"]:
        await deps.notify(state.progress, {"event": "tool_started", "tool": item["tool"], "arguments": {}})
        await deps.notify(state.progress, {"event": "tool_finished", **item})
    await deps.notify(state.progress, {
        "event": "stage", "stage": "validation",
        "message": "证据校验完成 · 必需证据 %s/%s · 结论强度 %s" % (
            result["evidence_validation"]["coverage"]["required_covered"],
            result["evidence_validation"]["coverage"]["required_total"],
            result["evidence_validation"]["allowed_conclusion_strength"],
        ),
        "validation": result["evidence_validation"],
    })
    await deps.notify(state.progress, {"event": "stage", "stage": "synthesis", "message": "正在汇总本地分析结果"})
    await deps.stream_answer(state.progress, result["answer"])
    result["model"] = "local-rules"
    result["model_health"] = {"requested_model_id": state.selected_model_id, "fallback_reason": reason, **state.model_health}
    result["usage"] = {}
    result["context_resolution"] = state.context_resolution.to_dict()
    return AvailabilityOutcome(state, result)


async def _ready_fallback(state: CoordinatorRunState, deps: "CoordinatorDependencies", reason: str) -> dict:
    await deps.notify(state.progress, {
        "event": "stage", "stage": "tools",
        "message": f"正在按依赖顺序执行 {len(state.execution_plan.steps)} 个已批准步骤",
        "execution_mode": "deterministic",
    })
    trace, observations, sources = await deps.execute_ready_plan(
        state.execution_plan, state.loop_guard, state.run_id, state.progress,
    )
    validation = deps.validate_evidence(state.execution_plan, state.selected_playbook, observations)
    contract = deps.create_answer_contract(
        validation, list(sources.values()), question=state.question,
        resolved_question=state.analysis_question,
    )
    synthesis = deps.ready_synthesis_fallback(
        validation, contract, observations, "模型未配置或模型熔断器当前阻止综合请求",
    )
    deps.emit_evidence_validation(state.run_id, 1, validation.to_dict())
    deps.emit_answer_synthesis(state.run_id, synthesis.report)
    await deps.notify(state.progress, {
        "event": "stage", "stage": "validation",
        "message": "证据校验完成 · 必需证据 %s/%s · 结论强度 %s" % (
            validation.coverage["required_covered"], validation.coverage["required_total"],
            validation.allowed_conclusion_strength,
        ),
        "validation": validation.to_dict(), "execution_mode": "deterministic",
    })
    await deps.notify(state.progress, {
        "event": "stage", "stage": "synthesis",
        "message": "模型综合不可用，正在输出证据安全的降级说明",
        "execution_mode": "deterministic_fallback",
    })
    await deps.stream_answer(state.progress, synthesis.answer)
    return deps.build_ready_model_unavailable_result(
        synthesis.answer, synthesis.report, trace=trace, route_payload=state.route_payload,
        playbook_payload=state.playbook_payload, plan_payload=state.plan_payload,
        loop_guard=state.loop_guard, evidence_validation=validation, answer_contract=contract,
        context_resolution=state.context_resolution, thinking=state.thinking,
        turn_decision=state.turn_decision, selected_model_id=state.selected_model_id,
        fallback_reason=reason, model_health=state.model_health, usage=state.context_usage,
    )
