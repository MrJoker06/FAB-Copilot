"""Model call with retry, health accounting and local fallback for one loop round."""

from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .failure import decide_model_failure

if TYPE_CHECKING:
    from ...model_gateway.gateway import ModelSessionPort
    from .agent_loop import AgentLoopContext
    from .loop_dispatch import LoopDispatchBinding
    from .loop_state import LoopRunState


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """The successful attempt of one round; later steps read its usage and timing."""

    assistant: dict
    usage: dict
    response_id: str | None
    stream_state: dict[str, Any]
    model_started: float


async def call_model(
    context: AgentLoopContext,
    state: LoopRunState,
    session: ModelSessionPort,
    request_payload: dict,
    iteration: int,
    dispatch_binding: LoopDispatchBinding | None,
) -> ModelTurn | dict:
    """Stream one round, retrying availability failures.

    Returns the successful turn, or the finished local-fallback result when the
    upstream stays unavailable before any answer body was emitted. Every other
    failure is re-raised unchanged from inside its ``except`` block.
    """
    settings = context.settings
    connection = context.connection
    run_id = context.run_id
    progress = context.progress
    thinking = context.thinking
    messages = context.messages
    emit = context.emit_event
    native_fallback = getattr(context, "native_fallback", None)
    retry_budget = 0 if context.main_recovery_trial else settings.model_max_retries
    for attempt in range(1, retry_budget + 2):
        model_started = time.perf_counter()
        emit(
            "model_call_started",
            run_id,
            phase="agent_loop",
            iteration=iteration + 1,
            attempt=attempt,
            model=connection.model,
            message_count=len(messages),
            thinking_requested=thinking,
            thinking_effective=thinking,
            reasoning_effort=request_payload.get("reasoning_effort"),
            full_content=(
                {"request": request_payload}
                if dispatch_binding is None
                else {
                    "request": {
                        "model": connection.model,
                        "message_count": len(messages),
                        "tool_count": len(request_payload.get("tools", [])),
                    }
                }
            ),
        )
        stream_state = {
            "answer_emitted": False,
            "suppress_embedded_tool_json": context.intent_route.intent
            == "general_knowledge",
            "required_disclosure": state.knowledge_fallback.get("disclosure") or "",
        }
        try:
            assistant, usage, response_id = await session.stream(
                request_payload,
                None if state.answer_contract.status == "required" else progress,
                stream_state,
            )
        except Exception as exc:
            failure_decision = decide_model_failure(
                availability_failure=context.retryable_model_error(exc),
                answer_emitted=stream_state["answer_emitted"],
                attempt=attempt,
                retry_budget=retry_budget,
            )
            availability_failure = failure_decision.availability_failure
            retryable = failure_decision.retryable
            will_retry = failure_decision.will_retry
            emit(
                "model_call_finished",
                run_id,
                status="error",
                iteration=iteration + 1,
                attempt=attempt,
                model=connection.model,
                duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
                error_type=type(exc).__name__,
                phase="agent_loop",
                retryable=retryable,
                will_retry=will_retry,
                answer_emitted=stream_state["answer_emitted"],
                content_length=int(stream_state.get("content_chars", 0)),
                thinking_requested=thinking,
                thinking_effective=thinking,
                reasoning_effort=request_payload.get("reasoning_effort"),
                failure_reason=context.model_failure_reason(exc),
                full_content=(
                    {"error_message": str(exc), "traceback": traceback.format_exc()}
                    if dispatch_binding is None
                    else {"error_type": type(exc).__name__}
                ),
            )
            if not will_retry:
                if availability_failure and context.health_enabled:
                    state.health, transition = context.record_model_failure(
                        context.selected_model_id,
                        context.model_error_category(exc),
                        threshold=settings.model_circuit_failure_threshold,
                        cooldown_seconds=settings.model_circuit_cooldown_seconds,
                    )
                    emit(
                        "model_health_failure_recorded",
                        run_id,
                        model_id=context.selected_model_id,
                        health=state.health,
                        transition=transition,
                    )
                if failure_decision.fallback_before_first_body and (
                    dispatch_binding is None or native_fallback is not None
                ):
                    return await _local_fallback(context, state, native_fallback)
                raise
            delay_seconds = context.model_retry_delay(
                settings.model_retry_base_seconds, attempt, exc
            )
            emit(
                "model_call_retry_scheduled",
                run_id,
                iteration=iteration + 1,
                attempt=attempt,
                next_attempt=attempt + 1,
                delay_ms=round(delay_seconds * 1000, 1),
                error_type=type(exc).__name__,
            )
            await context.notify(
                progress,
                {
                    "event": "stage",
                    "stage": "retrying",
                    "iteration": iteration + 1,
                    "attempt": attempt + 1,
                    "message": f"模型服务暂时不可用，正在进行第 {attempt + 1} 次请求",
                },
            )
            await asyncio.sleep(delay_seconds)
            continue
        emit(
            "model_call_finished",
            run_id,
            status="success",
            phase="agent_loop",
            iteration=iteration + 1,
            attempt=attempt,
            model=connection.model,
            duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            finish_reason=stream_state.get("finish_reason")
            or ("tool_calls" if assistant.get("tool_calls") else "stop"),
            response_id=response_id,
            first_content_ms=stream_state.get("first_content_ms"),
            max_content_gap_ms=stream_state.get("max_content_gap_ms", 0),
            content_delta_count=stream_state.get("content_delta_count", 0),
            content_chars=stream_state.get("content_chars", 0),
            stream_duration_ms=stream_state.get("stream_duration_ms"),
            reasoning_length=int(stream_state.get("reasoning_length", 0)),
            content_length=len(str(assistant.get("content") or "")),
            thinking_requested=thinking,
            thinking_effective=thinking,
            reasoning_effort=request_payload.get("reasoning_effort"),
            full_content=(
                {"response": context.audit_assistant(assistant)}
                if dispatch_binding is None
                else {
                    "response": {
                        "has_content": bool(assistant.get("content")),
                        "tool_call_count": len(assistant.get("tool_calls") or []),
                    }
                }
            ),
        )
        state.thinking_answer_effective = state.thinking_answer_effective or thinking
        if context.health_enabled:
            state.health, transition = context.record_model_success(
                context.selected_model_id
            )
            if transition:
                emit(
                    "model_circuit_recovered",
                    run_id,
                    model_id=context.selected_model_id,
                    health=state.health,
                )
        return ModelTurn(assistant, usage, response_id, stream_state, model_started)
    # Settings clamp the retry budget to >= 0, so the final attempt always
    # returns or raises above; only a negative injected budget reaches here.
    raise RuntimeError("model retry loop ended without a model turn")


async def _local_fallback(
    context: AgentLoopContext,
    state: LoopRunState,
    native_fallback: Callable[[], Awaitable[dict]] | None,
) -> dict:
    progress = context.progress
    selected_model_id = context.selected_model_id
    context_resolution = context.context_resolution
    context.emit_event(
        "model_local_fallback_activated",
        context.run_id,
        model_id=selected_model_id,
        reason="upstream_unavailable",
        health=state.health,
    )
    if native_fallback is not None:
        result = await native_fallback()
    else:
        result = context.offline_answer(
            context.analysis_question,
            context.intent_route,
            context.playbook_selection,
            context.execution_plan,
            context.loop_guard,
            context_resolution,
            fallback_reason="upstream_unavailable",
        )
    result.update(
        {
            "model": "local-rules",
            "usage": context.total_usage,
            "context_resolution": context_resolution.to_dict(),
            "model_health": {
                "requested_model_id": selected_model_id,
                "fallback_reason": "upstream_unavailable",
                **state.health,
            },
        }
    )
    if native_fallback is None:
        for item in result["tool_trace"]:
            await context.notify(
                progress,
                {"event": "tool_started", "tool": item["tool"], "arguments": {}},
            )
            await context.notify(progress, {"event": "tool_finished", **item})
    await context.stream_answer(progress, result["answer"])
    return result
