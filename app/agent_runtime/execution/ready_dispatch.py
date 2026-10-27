"""Dispatcher-backed execution for already-approved Ready plans."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from ...planning_runtime.contracts import ExecutionPlan, PlanBudget, PlanStep
from ..tools.contracts import ToolExecutionLimits, ToolResult, ToolStatus
from .loop_guard import ToolLoopGuard
from .ready_graph import ready_step_order
from .runtime_contracts import RuntimeContext, RuntimeContractError
from .runtime_ports import ToolDispatcherPort
from .tool_result_bridge import project_tool_result

_CONTRACT_ERROR = "Ready dispatch contract violated."


@dataclass(frozen=True, slots=True)
class ReadyDispatchBinding:
    plan: ExecutionPlan
    guard: ToolLoopGuard
    context: RuntimeContext
    dispatcher: ToolDispatcherPort
    raw_rows_for: Callable[[str], int | None]
    extract_sources: Callable[[ToolResult[object]], tuple[dict[str, object], ...]]
    cleanup: Callable[[], None]


@dataclass(frozen=True, slots=True)
class ReadyDispatchOutcome:
    trace: list[dict]
    observation_payloads: list[dict]
    sources: dict[str, dict]
    tool_results: tuple[ToolResult[object], ...]


def _contract_error() -> RuntimeContractError:
    return RuntimeContractError(_CONTRACT_ERROR)


def _remaining_calls(binding: ReadyDispatchBinding, start_calls: int) -> int | None:
    initial = binding.context.limits.remaining_calls
    if initial is None:
        return None
    return max(0, initial - (binding.guard.total_calls - start_calls))


def _limits(
    binding: ReadyDispatchBinding, step: PlanStep, start_calls: int
) -> ToolExecutionLimits:
    runtime_limit = binding.context.limits.max_result_rows
    limits = [binding.plan.budget.max_rows_per_call, step.estimated_result_limit]
    if runtime_limit is not None:
        limits.append(runtime_limit)
    return ToolExecutionLimits(
        remaining_calls=_remaining_calls(binding, start_calls),
        max_result_rows=max(0, min(limits)),
        deadline_monotonic=binding.context.limits.deadline_monotonic,
    )


def _result_is_for_step(result: object, call_id: str, tool: str) -> ToolResult[object]:
    if (
        not isinstance(result, ToolResult)
        or result.call_id != call_id
        or result.tool_name != tool
    ):
        raise _contract_error()
    return result


def _add_sources(
    target: dict[str, dict],
    extract_sources: Callable[[ToolResult[object]], tuple[dict[str, object], ...]],
    result: ToolResult[object],
) -> None:
    try:
        values = extract_sources(result)
    except Exception:  # noqa: BLE001 - source extraction details are not public
        raise _contract_error() from None
    if not isinstance(values, tuple):
        raise _contract_error()
    for value in values:
        if not isinstance(value, dict):
            raise _contract_error()
        key = value.get("reference_id")
        if not isinstance(key, str) or not key:
            raise _contract_error()
        target[key] = dict(value)


def _non_negative_limit(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_binding(
    plan: object,
    loop_guard: object,
    run_id: object,
    binding: object,
) -> bool:
    if (
        not isinstance(plan, ExecutionPlan)
        or not isinstance(loop_guard, ToolLoopGuard)
        or not isinstance(run_id, str)
        or not isinstance(binding, ReadyDispatchBinding)
        or not isinstance(binding.context, RuntimeContext)
        or binding.plan is not plan
        or binding.guard is not loop_guard
        or loop_guard.plan is not plan
        or binding.context.run_id != run_id
        or plan.status != "ready"
        or not isinstance(plan.budget, PlanBudget)
        or not _non_negative_limit(plan.budget.max_rows_per_call)
        or not callable(getattr(binding.dispatcher, "dispatch", None))
        or not callable(binding.raw_rows_for)
        or not callable(binding.extract_sources)
        or not callable(binding.cleanup)
    ):
        return False
    return all(
        isinstance(step, PlanStep) and _non_negative_limit(step.estimated_result_limit)
        for step in plan.steps
    )


async def execute_dispatched_ready_plan(
    plan: ExecutionPlan,
    loop_guard: ToolLoopGuard,
    run_id: str,
    progress: Any,
    *,
    binding: ReadyDispatchBinding,
    notify: Callable[[Any, dict], Awaitable[None]],
    emit_event: Callable[..., None],
) -> ReadyDispatchOutcome:
    """Execute Ready steps through one bound dispatcher without model selection."""
    if not _valid_binding(plan, loop_guard, run_id, binding):
        raise _contract_error()
    ordered_steps = ready_step_order(plan)
    started = time.perf_counter()
    start_calls = loop_guard.total_calls
    trace: list[dict] = []
    observations: list[dict] = []
    sources: dict[str, dict] = {}
    results: list[ToolResult[object]] = []
    outcomes: dict[str, str] = {}
    round_finished = False
    loop_guard.begin_round()
    try:
        emit_event(
            "ready_plan_execution_started",
            run_id,
            plan_id=plan.plan_id,
            step_count=len(ordered_steps),
            execution_mode="deterministic",
        )
        for step in ordered_steps:
            call_id = f"plan-{step.step_id}"
            failed_dependencies = tuple(
                dependency
                for dependency in step.depends_on
                if outcomes.get(dependency) != "success"
            )
            await notify(
                progress,
                {
                    "event": "tool_started",
                    "tool": step.tool,
                    "arguments": {},
                    "plan_step_id": step.step_id,
                    "execution_mode": "deterministic",
                },
            )
            emit_event(
                "tool_call_started",
                run_id,
                tool=step.tool,
                tool_call_id=call_id,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
            )
            if failed_dependencies:
                message = f"依赖步骤未成功：{', '.join(failed_dependencies)}"
                item = {
                    "call_id": call_id,
                    "tool": step.tool,
                    "arguments": {},
                    "plan_step_id": step.step_id,
                    "status": "blocked",
                    "error_code": "dependency_failed",
                    "error": message,
                    "execution_state": "not_started",
                    "execution_mode": "deterministic",
                }
                trace.append(item)
                observations.append(
                    {
                        "tool": step.tool,
                        "arguments": {},
                        "status": "blocked",
                        "error": message,
                        "source_ref": f"TOOL:{step.step_id}",
                    }
                )
                outcomes[step.step_id] = "blocked"
                await notify(progress, {"event": "tool_finished", **item})
                emit_event(
                    "tool_call_blocked",
                    run_id,
                    tool=step.tool,
                    tool_call_id=call_id,
                    plan_step_id=step.step_id,
                    execution_mode="deterministic",
                    reason_code="dependency_failed",
                )
                emit_event(
                    "tool_call_finished",
                    run_id,
                    status="blocked",
                    tool=step.tool,
                    plan_step_id=step.step_id,
                    execution_mode="deterministic",
                    error_code="dependency_failed",
                )
                continue
            context = replace(
                binding.context.for_tool_call(call_id, step.step_id),
                limits=_limits(binding, step, start_calls),
            )
            try:
                result = _result_is_for_step(
                    await binding.dispatcher.dispatch(
                        step.tool, dict(step.parameters), context
                    ),
                    call_id,
                    step.tool,
                )
            except asyncio.CancelledError:
                raise
            except RuntimeContractError:
                raise
            except Exception:  # noqa: BLE001 - dispatcher details are not public
                raise _contract_error() from None
            results.append(result)
            projection = project_tool_result(
                result,
                arguments=dict(step.parameters),
                step_id=step.step_id,
            )
            try:
                raw_rows = binding.raw_rows_for(call_id)
            except Exception:  # noqa: BLE001 - diagnostic callback details are not public
                raise _contract_error() from None
            if raw_rows is None and result.status is ToolStatus.SUCCEEDED:
                raw_rows = result.row_count
            if raw_rows is not None and (
                isinstance(raw_rows, bool)
                or not isinstance(raw_rows, int)
                or raw_rows < 0
            ):
                raise _contract_error()
            item = dict(projection.trace)
            item.update(
                {
                    "plan_step_id": step.step_id,
                    "execution_mode": "deterministic",
                    "raw_rows": raw_rows,
                    "rows": result.row_count,
                }
            )
            trace.append(item)
            observation = dict(projection.observation)
            observations.append(observation)
            _add_sources(sources, binding.extract_sources, result)
            status = item["status"]
            outcomes[step.step_id] = "success" if status == "ok" else status
            event = {
                **projection.event,
                "plan_step_id": step.step_id,
                "execution_mode": "deterministic",
                "raw_rows": raw_rows,
            }
            await notify(progress, event)
            emit_event(
                "tool_call_finished",
                run_id,
                status="success" if status == "ok" else status,
                tool=step.tool,
                tool_call_id=call_id,
                plan_step_id=step.step_id,
                execution_mode="deterministic",
                duration_ms=result.elapsed_ms,
                rows=result.row_count,
                raw_rows=raw_rows,
                error_code=result.error.code if result.error else None,
            )
        loop_guard.finish_round()
        round_finished = True
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
            succeeded=sum(value == "success" for value in outcomes.values()),
            failed=sum(value == "error" for value in outcomes.values()),
            blocked=sum(value == "blocked" for value in outcomes.values()),
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return ReadyDispatchOutcome(trace, observations, sources, tuple(results))
    finally:
        try:
            if not round_finished:
                loop_guard.finish_round()
        finally:
            binding.cleanup()
