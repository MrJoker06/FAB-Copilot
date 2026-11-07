"""Answer paths that end a model/tool loop run: text, submission and iteration limit."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from ..synthesis.ready import (
    SYNTHESIS_REPAIR_MAX_SECONDS,
    salvage_submit_analysis,
    valid_submit_analysis,
)
from .loop_state import add_usage

if TYPE_CHECKING:
    from ...model_gateway.gateway import ModelSessionPort
    from .agent_loop import AgentLoopContext
    from .loop_dispatch import LoopDispatchBinding
    from .loop_model_call import ModelTurn
    from .loop_response import LoopResponse
    from .loop_state import LoopRunState


def is_submission_round(
    classified_response: LoopResponse | None, tool_calls: list[Any]
) -> bool:
    return (
        classified_response is not None and classified_response.kind == "submission"
    ) or (
        classified_response is None
        and len(tool_calls) == 1
        and tool_calls[0].get("function", {}).get("name") == "submit_analysis"
    )


async def finish_text_answer(
    context: AgentLoopContext,
    state: LoopRunState,
    dispatch_binding: LoopDispatchBinding | None,
    turn: ModelTurn,
) -> dict:
    """Finalize a round whose response carried no tool calls."""
    assistant = turn.assistant
    intent_route = context.intent_route
    knowledge_fallback = state.knowledge_fallback
    answer_contract = state.answer_contract
    progress = context.progress
    raw_answer = assistant.get("content") or (
        context.loop_guard.termination_answer()
        if context.loop_guard.force_synthesis
        else "分析完成，但模型没有返回文字。"
    )
    if intent_route.intent == "general_knowledge":
        raw_answer = context.normalize_general_knowledge_answer(raw_answer)
    disclosure = knowledge_fallback.get("disclosure")
    if (
        knowledge_fallback["used"]
        and disclosure
        and not context.has_knowledge_fallback_disclosure(raw_answer)
    ):
        raw_answer = f"> {disclosure}\n\n{raw_answer}"
    synthesis = context.synthesize_legacy_answer(
        raw_answer, answer_contract, list(context.sources.values())
    )
    context.emit_answer_synthesis(context.run_id, synthesis.report)
    if (
        answer_contract.status == "required"
        or (
            intent_route.intent == "general_knowledge"
            and not turn.stream_state.get("answer_emitted")
        )
        or not assistant.get("content")
    ):
        await context.notify(
            progress,
            {
                "event": "stage",
                "stage": "synthesis",
                "message": "正在按证据等级整理结构化答案",
            },
        )
        await context.stream_answer(progress, synthesis.answer)
    return state.build_result(
        context, dispatch_binding, synthesis.answer, synthesis.report
    )


async def finish_submission(
    context: AgentLoopContext,
    state: LoopRunState,
    dispatch_binding: LoopDispatchBinding | None,
    session: ModelSessionPort,
    turn: ModelTurn,
    request_payload: dict,
    classified_response: LoopResponse | None,
    tool_calls: list[Any],
    iteration: int,
) -> dict:
    """Finalize a sole ``submit_analysis`` call, repairing or degrading invalid JSON."""
    raw_arguments = (
        classified_response.tool_calls[0].arguments
        if classified_response is not None
        else tool_calls[0].get("function", {}).get("arguments") or "{}"
    )
    submission_error: str | None = None
    try:
        submission = json.loads(raw_arguments)
        if not isinstance(submission, dict):
            raise ValueError("结构化答案必须是 JSON 对象")
    except Exception as exc:
        submission = {}
        submission_error = str(exc)
    if submission_error:
        return await _repair_submission(
            context,
            state,
            dispatch_binding,
            session,
            turn,
            request_payload,
            raw_arguments,
            submission_error,
            iteration,
        )
    synthesis = context.synthesize_submission(
        submission,
        state.answer_contract,
        list(context.sources.values()),
        status="structured" if submission else "repaired",
    )
    await context.notify(
        context.progress,
        {
            "event": "stage",
            "stage": "synthesis",
            "message": "结构化答案已通过证据约束，正在输出",
        },
    )
    context.emit_answer_synthesis(context.run_id, synthesis.report)
    await context.stream_answer(context.progress, synthesis.answer)
    return state.build_result(
        context, dispatch_binding, synthesis.answer, synthesis.report
    )


async def _repair_submission(
    context: AgentLoopContext,
    state: LoopRunState,
    dispatch_binding: LoopDispatchBinding | None,
    session: ModelSessionPort,
    turn: ModelTurn,
    request_payload: dict,
    raw_arguments: str,
    submission_error: str,
    iteration: int,
) -> dict:
    run_id = context.run_id
    progress = context.progress
    emit = context.emit_event
    answer_contract = state.answer_contract
    request_synthesis_correction = context.request_synthesis_correction
    emit(
        "answer_submission_rejected",
        run_id,
        iteration=iteration + 1,
        error_type="invalid_json",
        error_message=submission_error,
        execution_mode="synthesis_only",
        repair_reason="truncated_or_invalid_submit_analysis",
        repair_outcome="repair_requested",
    )
    original_token_cap = request_payload.get("max_tokens")
    if request_synthesis_correction is not None and original_token_cap is not None:
        (
            repaired,
            repair_usage,
            _repair_response_id,
            repair_outcome,
        ) = await request_synthesis_correction(
            session,
            context.connection,
            context.messages,
            raw_arguments,
            int(original_token_cap) - int(turn.usage.get("completion_tokens", 0) or 0),
            SYNTHESIS_REPAIR_MAX_SECONDS - (time.perf_counter() - turn.model_started),
            run_id,
            iteration + 1,
        )
    else:
        repaired, repair_usage, _repair_response_id, repair_outcome = (
            None,
            {},
            None,
            "unavailable_or_timeout",
        )
    add_usage(context.total_usage, repair_usage)
    if repaired is not None:
        submission = valid_submit_analysis(repaired)
        if submission is not None:
            repair_events = (
                {
                    "reason": "truncated_or_invalid_submit_analysis",
                    "affected_field": "submit_analysis",
                    "outcome": "model_correction_accepted",
                },
            )
            emit(
                "answer_submission_repair",
                run_id,
                iteration=iteration + 1,
                repair_reason="truncated_or_invalid_submit_analysis",
                repair_outcome=repair_outcome,
            )
            synthesis = context.synthesize_submission(
                submission,
                answer_contract,
                list(context.sources.values()),
                status="structured",
                repair_events=repair_events,
            )
            context.emit_answer_synthesis(run_id, synthesis.report)
            await context.stream_answer(progress, synthesis.answer)
            return state.build_result(
                context, dispatch_binding, synthesis.answer, synthesis.report
            )
        repair_outcome = "invalid_correction_response"
    await context.notify(
        progress,
        {
            "event": "stage",
            "stage": "synthesis",
            "message": "结构化答案不完整，正在保留已完成取证并安全降级",
        },
    )
    emit(
        "answer_submission_repair",
        run_id,
        iteration=iteration + 1,
        repair_reason="truncated_or_invalid_submit_analysis",
        repair_outcome=repair_outcome,
    )
    salvaged = salvage_submit_analysis(raw_arguments)
    if salvaged is not None:
        repair_events = tuple(salvaged.pop("_repair_events", ()))
        synthesis = context.synthesize_submission(
            salvaged,
            answer_contract,
            list(context.sources.values()),
            status="repaired",
            repair_events=repair_events,
        )
        context.emit_answer_synthesis(run_id, synthesis.report)
        await context.stream_answer(progress, synthesis.answer)
        return state.build_result(
            context, dispatch_binding, synthesis.answer, synthesis.report
        )
    synthesis = context.synthesize_legacy_answer(
        "模型提交的结构化结果不完整，服务端未重跑业务工具；"
        "请基于本次已完成取证重新提交分析。",
        answer_contract,
        list(context.sources.values()),
        repair_events=(
            {
                "reason": "truncated_or_invalid_submit_analysis",
                "affected_field": "submit_analysis",
                "outcome": repair_outcome,
            },
        ),
    )
    context.emit_answer_synthesis(run_id, synthesis.report)
    await context.stream_answer(progress, synthesis.answer)
    return state.build_result(
        context, dispatch_binding, synthesis.answer, synthesis.report
    )


async def finish_iteration_limit(
    context: AgentLoopContext,
    state: LoopRunState,
    dispatch_binding: LoopDispatchBinding | None,
) -> dict:
    """Terminate after the last allowed model round without a final answer."""
    loop_guard = context.loop_guard
    loop_guard.enter_synthesis(
        "model_iteration_limit",
        f"模型已达到 {loop_guard.max_model_iterations} 轮执行上限。",
    )
    answer = loop_guard.termination_answer()
    synthesis = context.synthesize_legacy_answer(
        answer, state.answer_contract, list(context.sources.values())
    )
    context.emit_answer_synthesis(context.run_id, synthesis.report)
    await context.stream_answer(context.progress, synthesis.answer)
    return state.build_result(
        context, dispatch_binding, synthesis.answer, synthesis.report
    )
