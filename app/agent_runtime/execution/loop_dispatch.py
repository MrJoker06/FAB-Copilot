"""One Dispatcher-backed business-tool round for the model loop."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from ...planning_runtime.contracts import ExecutionPlan, PlanBudget, PlanStep
from ..tools.contracts import ToolExecutionLimits, ToolResult, ToolStatus
from .loop_guard import ToolLoopGuard
from .loop_response import LoopResponse
from .runtime_contracts import ModelRequest, RuntimeContext, RuntimeContractError
from .runtime_ports import ToolDispatcherPort
from .tool_result_bridge import project_tool_result

_ERROR = "Loop dispatch contract violated."


@dataclass(frozen=True, slots=True)
class LoopDispatchBinding:
    plan: ExecutionPlan
    guard: ToolLoopGuard
    context: RuntimeContext
    dispatcher: ToolDispatcherPort
    raw_rows_for: Callable[[str], int | None]
    extract_sources: Callable[[ToolResult[object]], tuple[dict[str, object], ...]]
    cleanup: Callable[[], None]
    tools_json: str
    initial_total_calls: int


@dataclass(frozen=True, slots=True)
class LoopDispatchOutcome:
    trace: list[dict]
    observation_payloads: list[dict]
    sources: dict[str, dict]
    tool_results: tuple[ToolResult[object], ...]
    tool_messages: tuple[dict[str, str], ...]


def _bad() -> RuntimeContractError:
    return RuntimeContractError(_ERROR)


def _step(plan: ExecutionPlan, call: object) -> PlanStep | None:
    if not hasattr(call, "name") or not hasattr(call, "arguments"):
        return None
    try:
        arguments = json.loads(call.arguments)
    except (RecursionError, TypeError, ValueError, json.JSONDecodeError):
        return None
    for step in plan.steps:
        if step.tool == call.name and step.parameters == arguments:
            return step
    return None


def _limits(binding: LoopDispatchBinding, step: PlanStep | None) -> ToolExecutionLimits:
    values = [binding.plan.budget.max_rows_per_call]
    if step is not None:
        values.append(step.estimated_result_limit)
    if binding.context.limits.max_result_rows is not None:
        values.append(binding.context.limits.max_result_rows)
    initial = binding.context.limits.remaining_calls
    remaining = (
        None
        if initial is None
        else max(0, initial - (binding.guard.total_calls - binding.initial_total_calls))
    )
    return ToolExecutionLimits(
        remaining, min(values), binding.context.limits.deadline_monotonic
    )


def validate_loop_binding(
    plan: object, guard: object, run_id: object, binding: object
) -> bool:
    if not (
        isinstance(plan, ExecutionPlan)
        and isinstance(guard, ToolLoopGuard)
        and isinstance(run_id, str)
        and isinstance(binding, LoopDispatchBinding)
        and binding.plan is plan
        and binding.guard is guard
        and guard.plan is plan
        and isinstance(binding.context, RuntimeContext)
        and binding.context.run_id == run_id
        and type(binding.initial_total_calls) is int
        and binding.initial_total_calls >= 0
        and callable(getattr(binding.dispatcher, "dispatch", None))
        and callable(binding.raw_rows_for)
        and callable(binding.extract_sources)
        and callable(binding.cleanup)
        and isinstance(binding.tools_json, str)
        and isinstance(plan.budget, PlanBudget)
        and type(plan.budget.max_rows_per_call) is int
        and plan.budget.max_rows_per_call >= 0
        and binding.initial_total_calls <= guard.total_calls
    ):
        return False
    try:
        ModelRequest("loop-binding-validation", (), binding.tools_json)
        schema = json.loads(binding.tools_json)
    except (RecursionError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(schema, list) and all(
        isinstance(step, PlanStep)
        and type(step.estimated_result_limit) is int
        and step.estimated_result_limit >= 0
        for step in plan.steps
    )


async def execute_dispatched_loop_round(
    plan: ExecutionPlan,
    loop_guard: ToolLoopGuard,
    run_id: str,
    iteration: int,
    response: LoopResponse,
    progress: Any,
    *,
    binding: LoopDispatchBinding,
    notify: Callable[[Any, dict], Awaitable[None]],
    emit_event: Callable[..., None],
) -> LoopDispatchOutcome:
    """Run only business calls; submission handling remains owned by the legacy loop."""
    if (
        not validate_loop_binding(plan, loop_guard, run_id, binding)
        or type(iteration) is not int
        or iteration < 1
        or not isinstance(response, LoopResponse)
        or response.kind not in {"tools", "mixed"}
    ):
        raise _bad()
    trace: list[dict] = []
    observations: list[dict] = []
    sources: dict[str, dict] = {}
    results: list[ToolResult[object]] = []
    messages: list[dict[str, str]] = []
    finished = False
    loop_guard.begin_round()
    try:
        for call in response.tool_calls:
            if call.name == "submit_analysis":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.call_id,
                        "content": json.dumps(
                            {
                                "ok": False,
                                "error_code": "SUBMISSION_MIXED",
                                "error": "submit_analysis 必须单独调用，不能与数据工具处于同一轮。",
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
        for index, call in enumerate(
            (c for c in response.tool_calls if c.name != "submit_analysis"), 1
        ):
            call_id = f"loop-{iteration}-{index}"
            step = _step(plan, call)
            await notify(
                progress,
                {
                    "event": "tool_started",
                    "tool": call.name,
                    "arguments": {},
                    "execution_mode": "model_loop",
                },
            )
            emit_event(
                "tool_call_started",
                run_id,
                tool=call.name,
                tool_call_id=call_id,
                model_tool_call_id=call.call_id,
                execution_mode="model_loop",
            )
            context = replace(
                binding.context.for_tool_call(call_id, step.step_id if step else None),
                limits=_limits(binding, step),
            )
            try:
                result = await binding.dispatcher.dispatch(
                    call.name, call.arguments, context
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - dispatcher details are not public
                raise _bad() from None
            if (
                not isinstance(result, ToolResult)
                or result.call_id != call_id
                or result.tool_name != call.name
            ):
                raise _bad()
            results.append(result)
            try:
                safe_arguments = json.loads(call.arguments)
            except (RecursionError, TypeError, ValueError, json.JSONDecodeError):
                safe_arguments = {}
            if not isinstance(safe_arguments, dict):
                safe_arguments = {}
            projection = project_tool_result(
                result,
                arguments=safe_arguments
                if result.status is ToolStatus.SUCCEEDED
                else {},
                step_id=step.step_id if step else call_id,
            )
            try:
                raw_rows = binding.raw_rows_for(call_id)
                extracted = binding.extract_sources(result)
            except Exception:  # noqa: BLE001 - callbacks are service-owned boundaries
                raise _bad() from None
            if raw_rows is None and result.status is ToolStatus.SUCCEEDED:
                raw_rows = result.row_count
            if raw_rows is not None and (type(raw_rows) is not int or raw_rows < 0):
                raise _bad()
            if not isinstance(extracted, tuple):
                raise _bad()
            for source in extracted:
                if (
                    not isinstance(source, dict)
                    or not isinstance(source.get("reference_id"), str)
                    or not source["reference_id"]
                ):
                    raise _bad()
                sources[source["reference_id"]] = dict(source)
            item = dict(projection.trace)
            item.update(
                {
                    "execution_mode": "model_loop",
                    "model_tool_call_id": call.call_id,
                    "raw_rows": raw_rows,
                    "rows": result.row_count,
                }
            )
            trace.append(item)
            observations.append(dict(projection.observation))
            event = {
                **projection.event,
                "execution_mode": "model_loop",
                "model_tool_call_id": call.call_id,
                "raw_rows": raw_rows,
            }
            await notify(progress, event)
            emit_event(
                "tool_call_finished",
                run_id,
                status="success" if item["status"] == "ok" else item["status"],
                tool=call.name,
                tool_call_id=call_id,
                model_tool_call_id=call.call_id,
                execution_mode="model_loop",
                rows=result.row_count,
                raw_rows=raw_rows,
                error_code=result.error.code if result.error else None,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.call_id,
                    "content": json.dumps(
                        {
                            "ok": result.status is ToolStatus.SUCCEEDED,
                            "data": result.data
                            if result.status is ToolStatus.SUCCEEDED
                            else None,
                            "error_code": result.error.code if result.error else None,
                            "execution_state": result.execution_state.value,
                            "error": result.error.public_message
                            if result.error
                            else None,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )
        loop_guard.finish_round()
        finished = True
        return LoopDispatchOutcome(
            trace, observations, sources, tuple(results), tuple(messages)
        )
    finally:
        try:
            if not finished:
                loop_guard.finish_round()
        finally:
            binding.cleanup()
