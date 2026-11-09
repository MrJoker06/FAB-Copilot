"""Post-round evidence validation, answer contract refresh and round audit."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.tool_result_projection import truncation_notices

if TYPE_CHECKING:
    from .agent_loop import AgentLoopContext
    from .loop_dispatch import LoopDispatchBinding
    from .loop_state import LoopRunState


async def validate_round(
    context: AgentLoopContext,
    state: LoopRunState,
    dispatch_binding: LoopDispatchBinding | None,
    iteration: int,
) -> None:
    """Re-validate evidence after a tool round and prepare the next round's contract."""
    run_id = context.run_id
    progress = context.progress
    messages = context.messages
    sources = context.sources
    intent_route = context.intent_route
    execution_plan = context.execution_plan
    loop_guard = context.loop_guard
    emit = context.emit_event
    evidence_validation = context.validate_evidence(
        execution_plan, context.selected_playbook, context.evidence_observations
    )
    state.evidence_validation = evidence_validation
    coverage = evidence_validation.coverage
    if (
        execution_plan.status == "ready"
        and coverage["required_total"] > 0
        and coverage["required_covered"] == coverage["required_total"]
    ):
        loop_guard.enter_synthesis(
            "required_evidence_complete",
            f"执行计划的 {coverage['required_total']} 组必需证据已全部覆盖。",
        )
    if intent_route.intent != "general_knowledge":
        state.knowledge_fallback = context.knowledge_fallback_state(
            intent_route, context.evidence_observations, sources
        )
    knowledge_fallback = state.knowledge_fallback
    answer_contract = context.create_answer_contract(
        evidence_validation,
        list(sources.values()),
        allow_model_knowledge_fallback=knowledge_fallback["used"],
        question=context.question,
        resolved_question=context.analysis_question,
        extra_limitations=truncation_notices(context.evidence_observations),
    )
    state.answer_contract = answer_contract
    messages.append(
        {
            "role": "system",
            "content": context.validator_system_message(evidence_validation),
        }
    )
    messages.append(
        {
            "role": "system",
            "content": context.synthesizer_system_message(answer_contract),
        }
    )
    await context.notify(
        progress,
        {
            "event": "stage",
            "stage": "validation",
            "message": (
                "证据校验完成 · "
                f"必需证据 {evidence_validation.coverage['required_covered']}/"
                f"{evidence_validation.coverage['required_total']} · "
                f"结论强度 {evidence_validation.allowed_conclusion_strength}"
            ),
            "validation": evidence_validation.to_dict(),
        },
    )
    context.emit_evidence_validation(
        run_id, iteration + 1, evidence_validation.to_dict()
    )
    if knowledge_fallback["used"] and not state.fallback_announced:
        state.fallback_announced = True
        emit(
            "knowledge_fallback_enabled",
            run_id,
            reason=knowledge_fallback["reason"],
            model=context.connection.model,
        )
        await context.notify(
            progress,
            {
                "event": "stage",
                "stage": "knowledge_fallback",
                "message": "知识库未检索到相关内容，正在使用模型通用知识补充回答",
                "knowledge_fallback": knowledge_fallback,
            },
        )
    guard_summary = loop_guard.summary()
    emit(
        "loop_guard_round_finished",
        run_id,
        iteration=iteration + 1,
        total_calls=guard_summary["total_calls"],
        unique_evidence_results=guard_summary["unique_evidence_results"],
        blocked_calls=guard_summary["blocked_calls"],
        consecutive_no_progress_rounds=guard_summary["consecutive_no_progress_rounds"],
        force_synthesis=guard_summary["force_synthesis"],
        stop_reason=guard_summary["stop_reason"],
    )
    if dispatch_binding is not None:
        state.sync_to_context(context)
