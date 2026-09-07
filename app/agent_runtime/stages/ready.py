"""Deterministic ready-plan synthesis stage."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .model import build_result
from ..coordinator_state import CoordinatorRunState

if TYPE_CHECKING:
    from ..dependencies import CoordinatorDependencies


async def execute_ready_synthesis(
    state: CoordinatorRunState, *, deps: "CoordinatorDependencies",
) -> dict | None:
    """Execute a ready plan and synthesize its evidence-bound answer.

    A non-ready plan is deliberately left for the model/tool loop stage.
    """
    if state.execution_plan.status != "ready":
        return None

    await deps.notify(state.progress, {
        "event": "stage", "stage": "tools",
        "message": f"正在按依赖顺序执行 {len(state.execution_plan.steps)} 个已批准步骤",
        "execution_mode": "deterministic",
    })
    state.trace, state.evidence_observations, state.sources = await deps.execute_ready_plan(
        state.execution_plan, state.loop_guard, state.run_id, state.progress,
    )
    state.evidence_validation = deps.validate_evidence(
        state.execution_plan, state.selected_playbook, state.evidence_observations,
    )
    state.knowledge_fallback = deps.knowledge_fallback_state(
        state.intent_route, state.evidence_observations, state.sources,
    )
    state.answer_contract = deps.create_answer_contract(
        state.evidence_validation, list(state.sources.values()),
        allow_model_knowledge_fallback=state.knowledge_fallback["used"],
    )
    deps.emit_evidence_validation(state.run_id, 1, state.evidence_validation.to_dict())
    await deps.notify(state.progress, {
        "event": "stage", "stage": "validation",
        "message": (
            "证据校验完成 · "
            f"必需证据 {state.evidence_validation.coverage['required_covered']}/"
            f"{state.evidence_validation.coverage['required_total']} · "
            f"结论强度 {state.evidence_validation.allowed_conclusion_strength}"
        ),
        "validation": state.evidence_validation.to_dict(), "execution_mode": "deterministic",
    })
    if state.knowledge_fallback["used"]:
        state.fallback_announced = True
        deps.emit(
            "knowledge_fallback_enabled", state.run_id,
            reason=state.knowledge_fallback["reason"], model=state.connection.model,
        )
        await deps.notify(state.progress, {
            "event": "stage", "stage": "knowledge_fallback",
            "message": "知识库未检索到相关内容，正在使用模型通用知识补充回答",
            "knowledge_fallback": state.knowledge_fallback,
        })
    await deps.notify(state.progress, {
        "event": "stage", "stage": "synthesis",
        "message": "计划工具已执行完毕，正在基于已验证证据生成结论",
        "execution_mode": "synthesis_only",
    })
    messages = deps.ready_synthesis_messages(
        state.analysis_question, state.execution_plan, state.evidence_validation,
        state.answer_contract, state.evidence_observations,
    )
    retry_budget = 0 if state.main_recovery_trial else state.settings.model_max_retries
    try:
        async with deps.async_client(timeout=state.settings.api_timeout_seconds) as client:
            assistant, usage, _, _ = await deps.request_ready_synthesis(
                client, state.endpoint,
                {"Authorization": f"Bearer {state.connection.api_key}", "Content-Type": "application/json"},
                state.connection, state.settings, messages, state.run_id, state.thinking, retry_budget,
            )
        for key in state.total_usage:
            state.total_usage[key] += int(usage.get(key, 0) or 0)
        state.thinking_answer_effective = state.thinking_answer_effective or state.thinking
        if state.health_enabled:
            state.health, transition = deps.record_model_success(state.selected_model_id)
            if transition:
                deps.emit("model_circuit_recovered", state.run_id, model_id=state.selected_model_id, health=state.health)
        synthesis = deps.synthesize_ready_assistant(
            assistant, state.answer_contract, list(state.sources.values()), state.evidence_validation,
            state.evidence_observations, state.run_id,
        )
    except Exception as exc:
        if deps.retryable_model_error(exc) and state.health_enabled:
            state.health, transition = deps.record_model_failure(
                state.selected_model_id, deps.model_error_category(exc),
                threshold=state.settings.model_circuit_failure_threshold,
                cooldown_seconds=state.settings.model_circuit_cooldown_seconds,
            )
            deps.emit(
                "model_health_failure_recorded", state.run_id, model_id=state.selected_model_id,
                health=state.health, transition=transition,
            )
        deps.emit(
            "model_local_fallback_activated", state.run_id, model_id=state.selected_model_id,
            reason="ready_synthesis_unavailable", health=state.health,
        )
        synthesis = deps.ready_synthesis_fallback(
            state.evidence_validation, state.answer_contract, state.evidence_observations,
            "模型综合服务暂时不可用",
        )
    deps.emit_answer_synthesis(state.run_id, synthesis.report)
    await deps.stream_answer(state.progress, synthesis.answer)
    result = build_result(state, deps, synthesis.answer, synthesis.report)
    result["execution_mode"] = "deterministic_ready_plan"
    result["model_tool_selection_calls"] = 0
    if synthesis.report.status != "structured":
        result["mode"] = "deterministic-fallback"
    return result
