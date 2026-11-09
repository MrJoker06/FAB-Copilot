"""Business-tool execution for one model/tool loop round (dispatched and legacy)."""

from __future__ import annotations

import json
import time
import traceback
from typing import TYPE_CHECKING, Any

from .loop_dispatch import execute_dispatched_loop_round
from ...core.tool_result_projection import prompt_content

if TYPE_CHECKING:
    from .agent_loop import AgentLoopContext
    from .loop_dispatch import LoopDispatchBinding
    from .loop_response import LoopResponse


async def execute_tool_round(
    context: AgentLoopContext,
    dispatch_binding: LoopDispatchBinding | None,
    classified_response: LoopResponse | None,
    tool_calls: list[Any],
    iteration: int,
) -> None:
    """Run the round's business tools and append their tool messages.

    The dispatched path hands tool calls to the bound Dispatcher; the legacy
    path executes registered handlers under the loop guard's round accounting.
    """
    loop_guard = context.loop_guard
    if dispatch_binding is not None:
        response = classified_response
        if response.kind in {"tools", "mixed"}:
            outcome = await execute_dispatched_loop_round(
                context.execution_plan,
                loop_guard,
                context.run_id,
                iteration + 1,
                response,
                context.progress,
                binding=dispatch_binding,
                notify=context.notify,
                emit_event=context.emit_event,
            )
            context.trace.extend(outcome.trace)
            context.evidence_observations.extend(
                context.evidence_observation_type(**item)
                for item in outcome.observation_payloads
            )
            context.sources.update(outcome.sources)
            context.messages.extend(outcome.tool_messages)
            tool_calls = []

    if dispatch_binding is None:
        loop_guard.begin_round()
    for call in tool_calls:
        await _execute_legacy_call(context, call)
    if dispatch_binding is None:
        loop_guard.finish_round()


async def _execute_legacy_call(context: AgentLoopContext, call: dict) -> None:
    run_id = context.run_id
    progress = context.progress
    messages = context.messages
    trace = context.trace
    sources = context.sources
    evidence_observations = context.evidence_observations
    loop_guard = context.loop_guard
    emit = context.emit_event
    notify = context.notify
    EvidenceObservation = context.evidence_observation_type
    function = call.get("function", {})
    name = function.get("name", "")
    tool_started = time.perf_counter()
    raw_arguments = function.get("arguments") or "{}"
    arguments, parse_error = context.parse_tool_arguments(raw_arguments)

    if name == "submit_analysis":
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.get("id") or "submit-analysis-rejected",
                "content": json.dumps(
                    {
                        "ok": False,
                        "error": "submit_analysis 必须单独调用，不能与数据工具处于同一轮。",
                    },
                    ensure_ascii=False,
                ),
            }
        )
        return

    await notify(
        progress, {"event": "tool_started", "tool": name, "arguments": arguments}
    )
    emit(
        "tool_call_started",
        run_id,
        tool=name or "unknown",
        tool_call_id=call.get("id"),
        full_content={"arguments": arguments},
    )
    decision = loop_guard.check_call(name or "unknown", arguments)
    if not decision.allowed:
        tool_duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
        blocked_item = {
            "tool": name or "unknown",
            "arguments": arguments,
            "status": "blocked",
            "error_code": decision.reason_code,
            "error": decision.message,
            "duration_ms": tool_duration_ms,
        }
        trace.append(blocked_item)
        evidence_observations.append(
            EvidenceObservation(
                name or "unknown",
                arguments,
                "blocked",
                error=decision.message,
            )
        )
        await notify(progress, {"event": "tool_finished", **blocked_item})
        emit(
            "tool_call_blocked",
            run_id,
            tool=name or "unknown",
            tool_call_id=call.get("id"),
            reason_code=decision.reason_code,
            signature_hash=decision.signature_hash,
            duration_ms=tool_duration_ms,
            full_content={"arguments": arguments, "message": decision.message},
        )
        emit(
            "tool_call_finished",
            run_id,
            status="blocked",
            tool=name or "unknown",
            duration_ms=tool_duration_ms,
            error_code=decision.reason_code,
        )
        content = json.dumps(
            {
                "ok": False,
                "error_code": decision.reason_code,
                "error": decision.message,
            },
            ensure_ascii=False,
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.get("id") or decision.signature_hash,
                "content": content,
            }
        )
        return

    try:
        if parse_error is not None:
            raise ValueError(f"工具参数不是有效 JSON 对象: {parse_error}")
        result = context.execute_tool(name, arguments)
        if name == "search_knowledge":
            raw_count = len(result) if isinstance(result, list) else 0
            result = (
                [
                    item
                    for item in result
                    if isinstance(item, dict)
                    and context.usable_knowledge_result(
                        str(arguments.get("query") or ""), item
                    )
                ]
                if isinstance(result, list)
                else []
            )
            if len(result) != raw_count:
                emit(
                    "knowledge_results_filtered",
                    run_id,
                    raw_count=raw_count,
                    usable_count=len(result),
                    filtered_count=raw_count - len(result),
                )
            for source in result:
                sources[source["reference_id"]] = source
        loop_guard.record_result(name, result, True)
        planned_step = next(
            (
                step
                for step in context.execution_plan.steps
                if step.tool == name and step.parameters == arguments
            ),
            None,
        )
        evidence_observations.append(
            EvidenceObservation(
                name,
                arguments,
                "success",
                result,
                source_ref=f"TOOL:{planned_step.step_id}"
                if planned_step
                else f"TOOL:{call.get('id') or name}",
            )
        )
        row_count = len(result) if isinstance(result, list) else 1
        tool_duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
        trace.append(
            {
                "tool": name,
                "arguments": arguments,
                "status": "ok",
                "rows": row_count,
                "duration_ms": tool_duration_ms,
            }
        )
        await notify(
            progress,
            {
                "event": "tool_finished",
                "tool": name,
                "arguments": arguments,
                "status": "ok",
                "rows": row_count,
                "duration_ms": tool_duration_ms,
            },
        )
        emit(
            "tool_call_finished",
            run_id,
            status="success",
            tool=name,
            duration_ms=tool_duration_ms,
            rows=row_count,
            full_content={"result": result},
        )
        content = prompt_content(name, result)
    except Exception as exc:
        loop_guard.record_result(name or "unknown", None, False)
        evidence_observations.append(
            EvidenceObservation(
                name or "unknown",
                arguments,
                "error",
                error=str(exc),
                source_ref=f"TOOL:{call.get('id') or name or 'unknown'}",
            )
        )
        trace.append(
            {
                "tool": name or "unknown",
                "arguments": arguments,
                "status": "error",
                "error": str(exc),
            }
        )
        await notify(
            progress,
            {
                "event": "tool_finished",
                "tool": name or "unknown",
                "arguments": arguments,
                "status": "error",
                "error": str(exc),
            },
        )
        emit(
            "tool_call_finished",
            run_id,
            status="error",
            tool=name or "unknown",
            duration_ms=round((time.perf_counter() - tool_started) * 1000, 1),
            error_type=type(exc).__name__,
            full_content={
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
        content = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    messages.append(
        {
            "role": "tool",
            "tool_call_id": call.get("id") or decision.signature_hash,
            "content": content,
        }
    )
