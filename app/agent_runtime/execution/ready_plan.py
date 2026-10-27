"""Deterministic execution for approved ready plans."""

from __future__ import annotations

import time
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from ...evidence.validator import EvidenceObservation
from ...planning_runtime.contracts import ExecutionPlan
from .loop_guard import ToolLoopGuard
from .ready_dispatch import ReadyDispatchBinding
from .ready_graph import ready_step_order


async def execute_ready_plan(
    plan: ExecutionPlan,
    loop_guard: ToolLoopGuard,
    run_id: str,
    progress: Any,
    *,
    notify: Callable[[Any, dict[str, Any]], Awaitable[None]],
    emit_event: Callable[..., None],
    usable_knowledge_result: Callable[[str, dict[str, Any]], bool],
    execute_tool: Callable[[str, dict[str, Any]], Any] | None = None,
    dispatch_binding: ReadyDispatchBinding | None = None,
) -> tuple[list[dict[str, Any]], list[EvidenceObservation], dict[str, dict[str, Any]]]:
    """Execute an approved ready plan without asking the model to select tools."""
    if dispatch_binding is not None:
        if execute_tool is not None:
            raise ValueError("dispatch_binding cannot be combined with execute_tool")
        from .ready_dispatch import execute_dispatched_ready_plan

        outcome = await execute_dispatched_ready_plan(
            plan, loop_guard, run_id, progress, binding=dispatch_binding,
            notify=notify, emit_event=emit_event,
        )
        observations = [
            EvidenceObservation(**payload) for payload in outcome.observation_payloads
        ]
        return outcome.trace, observations, outcome.sources
    if execute_tool is None:
        raise ValueError("execute_tool is required without dispatch_binding")
    execution_started = time.perf_counter()
    ordered_steps = ready_step_order(plan)
    trace: list[dict[str, Any]] = []
    observations: list[EvidenceObservation] = []
    sources: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, str] = {}
    emit_event(
        "ready_plan_execution_started",
        run_id,
        plan_id=plan.plan_id,
        step_count=len(ordered_steps),
        execution_mode="deterministic",
    )
    loop_guard.begin_round()

    for step in ordered_steps:
        arguments = dict(step.parameters)
        tool_started = time.perf_counter()
        failed_dependencies = tuple(
            dependency
            for dependency in step.depends_on
            if outcomes.get(dependency) != "success"
        )
        await notify(progress, {
            "event": "tool_started",
            "tool": step.tool,
            "arguments": arguments,
            "plan_step_id": step.step_id,
            "execution_mode": "deterministic",
        })
        emit_event(
            "tool_call_started",
            run_id,
            tool=step.tool,
            tool_call_id=f"plan-{step.step_id}",
            plan_step_id=step.step_id,
            execution_mode="deterministic",
            full_content={"arguments": arguments},
        )

        if failed_dependencies:
            message = f"依赖步骤未成功：{', '.join(failed_dependencies)}"
            duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
            item = {
                "tool": step.tool,
                "arguments": arguments,
                "plan_step_id": step.step_id,
                "status": "blocked",
                "error_code": "dependency_failed",
                "error": message,
                "duration_ms": duration_ms,
                "execution_mode": "deterministic",
            }
            trace.append(item)
            observations.append(EvidenceObservation(
                step.tool,
                arguments,
                "blocked",
                error=message,
                source_ref=f"TOOL:{step.step_id}",
            ))
            outcomes[step.step_id] = "blocked"
            await notify(progress, {"event": "tool_finished", **item})
            emit_event(
                "tool_call_blocked",
                run_id,
                tool=step.tool,
                tool_call_id=f"plan-{step.step_id}",
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                reason_code="dependency_failed",
                duration_ms=duration_ms,
                full_content={"arguments": arguments, "message": message},
            )
            emit_event(
                "tool_call_finished",
                run_id,
                status="blocked",
                tool=step.tool,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                duration_ms=duration_ms,
                error_code="dependency_failed",
            )
            continue

        decision = loop_guard.check_call(step.tool, arguments)
        if not decision.allowed:
            duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
            item = {
                "tool": step.tool,
                "arguments": arguments,
                "plan_step_id": step.step_id,
                "status": "blocked",
                "error_code": decision.reason_code,
                "error": decision.message,
                "duration_ms": duration_ms,
                "execution_mode": "deterministic",
            }
            trace.append(item)
            observations.append(EvidenceObservation(
                step.tool,
                arguments,
                "blocked",
                error=decision.message,
                source_ref=f"TOOL:{step.step_id}",
            ))
            outcomes[step.step_id] = "blocked"
            await notify(progress, {"event": "tool_finished", **item})
            emit_event(
                "tool_call_blocked",
                run_id,
                tool=step.tool,
                tool_call_id=f"plan-{step.step_id}",
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                reason_code=decision.reason_code,
                signature_hash=decision.signature_hash,
                duration_ms=duration_ms,
                full_content={"arguments": arguments, "message": decision.message},
            )
            emit_event(
                "tool_call_finished",
                run_id,
                status="blocked",
                tool=step.tool,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                duration_ms=duration_ms,
                error_code=decision.reason_code,
            )
            continue

        try:
            result = execute_tool(step.tool, arguments)
            raw_rows = len(result) if isinstance(result, list) else (1 if result is not None else 0)
            if step.tool == "search_knowledge":
                result = [
                    item for item in result
                    if isinstance(item, dict)
                    and usable_knowledge_result(str(arguments.get("query") or ""), item)
                ] if isinstance(result, list) else []
            if isinstance(result, list):
                result_limit = min(plan.budget.max_rows_per_call, step.estimated_result_limit)
                result = result[:max(0, result_limit)]
            if step.tool == "search_knowledge":
                for source in result:
                    reference_id = str(source.get("reference_id") or "")
                    if reference_id:
                        sources[reference_id] = source
            loop_guard.record_result(step.tool, result, True)
            observations.append(EvidenceObservation(
                step.tool,
                arguments,
                "success",
                result,
                source_ref=f"TOOL:{step.step_id}",
            ))
            row_count = len(result) if isinstance(result, list) else (1 if result is not None else 0)
            duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
            item = {
                "tool": step.tool,
                "arguments": arguments,
                "plan_step_id": step.step_id,
                "status": "ok",
                "rows": row_count,
                "raw_rows": raw_rows,
                "duration_ms": duration_ms,
                "execution_mode": "deterministic",
            }
            trace.append(item)
            outcomes[step.step_id] = "success"
            await notify(progress, {"event": "tool_finished", **item})
            emit_event(
                "tool_call_finished",
                run_id,
                status="success",
                tool=step.tool,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                duration_ms=duration_ms,
                rows=row_count,
                raw_rows=raw_rows,
                full_content={"result": result},
            )
        except Exception as exc:
            loop_guard.record_result(step.tool, None, False)
            observations.append(EvidenceObservation(
                step.tool,
                arguments,
                "error",
                error=str(exc),
                source_ref=f"TOOL:{step.step_id}",
            ))
            duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
            item = {
                "tool": step.tool,
                "arguments": arguments,
                "plan_step_id": step.step_id,
                "status": "error",
                "error": str(exc),
                "duration_ms": duration_ms,
                "execution_mode": "deterministic",
            }
            trace.append(item)
            outcomes[step.step_id] = "error"
            await notify(progress, {"event": "tool_finished", **item})
            emit_event(
                "tool_call_finished",
                run_id,
                status="error",
                tool=step.tool,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
            )

    loop_guard.finish_round()
    if not loop_guard.force_synthesis:
        loop_guard.enter_synthesis(
            "deterministic_plan_completed",
            "确定性 ready 计划已完成，禁止继续选择业务工具。",
        )
    emit_event(
        "ready_plan_execution_finished",
        run_id,
        plan_id=plan.plan_id,
        execution_mode="deterministic",
        succeeded=sum(status == "success" for status in outcomes.values()),
        failed=sum(status == "error" for status in outcomes.values()),
        blocked=sum(status == "blocked" for status in outcomes.values()),
        duration_ms=round((time.perf_counter() - execution_started) * 1000, 1),
    )
    return trace, observations, sources
