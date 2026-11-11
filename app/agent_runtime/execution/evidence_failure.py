"""Terminal Runtime response when required business evidence cannot be checked."""

from __future__ import annotations


async def finish_check_failure(context, state, dispatch_binding):
    """Finish without another model or Tool call, before or after a tool round."""
    context.loop_guard.enter_synthesis(
        "evidence_check_failed", "必需证据检查不可用，不能形成已验证诊断。"
    )
    synthesis = context.synthesize_legacy_answer(
        "本次证据检查不可用，不能给出已验证的生产诊断。请核对证据策略及来源后重试；"
        "本次不会自动重跑业务工具或用模型知识替代检查。",
        state.answer_contract,
        list(context.sources.values()),
    )
    context.emit_answer_synthesis(context.run_id, synthesis.report)
    await context.stream_answer(context.progress, synthesis.answer)
    result = state.build_result(
        context, dispatch_binding, synthesis.answer, synthesis.report
    )
    result["mode"] = "deterministic-fallback"
    return result
