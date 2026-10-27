"""Explicit assembly checks for Dispatcher-backed model-loop rounds."""

from __future__ import annotations

import json

from ..agent_runtime.application import AgentRun
from ..agent_runtime.execution.loop_dispatch import LoopDispatchBinding
from ..agent_runtime.execution.loop_guard import ToolLoopGuard
from ..agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from ..agent_runtime.execution.runtime_contracts import ModelRequest, RuntimeContext
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.dispatcher import ToolDispatcher
from ..agent_runtime.tools.tool_registry import LegacyBindingAdapter
from ..planning_runtime.contracts import ExecutionPlan
from .agent_assembly import AssemblyError


def bind_loop_dispatcher(
    plan: ExecutionPlan,
    guard: ToolLoopGuard,
    context: RuntimeContext,
    dispatcher: ToolDispatcher,
    projector: ReadyResultPolicy,
) -> LoopDispatchBinding:
    """Bind exactly one guard budget and only the assembled business schema."""
    if not (
        isinstance(plan, ExecutionPlan)
        and isinstance(guard, ToolLoopGuard)
        and isinstance(context, RuntimeContext)
        and isinstance(dispatcher, ToolDispatcher)
        and isinstance(projector, ReadyResultPolicy)
        and guard.plan is plan
        and context.run_id == dispatcher.run_id
        and isinstance(dispatcher.budget, LoopGuardToolBudget)
        and dispatcher.budget.guard is guard
        and dispatcher.result_policy is projector
    ):
        raise AssemblyError()
    try:
        schema = []
        for item in dispatcher.registry.model_tools:
            if not isinstance(item, dict) or not isinstance(item.get("function"), dict):
                continue
            name = item["function"].get("name")
            if not isinstance(name, str) or name not in dispatcher.allowed_tools:
                continue
            binding = dispatcher.registry.resolve(name)
            if (
                isinstance(binding, LegacyBindingAdapter)
                and name not in dispatcher.legacy_tools
            ):
                continue
            if name != "submit_analysis":
                schema.append(item)
        if "submit_analysis" in dispatcher.allowed_tools:
            raise ValueError
        tools_json = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        ModelRequest("loop-binding-validation", (), tools_json)
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        raise AssemblyError() from None
    return LoopDispatchBinding(
        plan,
        guard,
        context,
        dispatcher,
        projector.take_raw_rows,
        projector.extract_sources,
        projector.clear,
        tools_json,
        guard.total_calls,
    )


def bind_loop_run(
    plan: ExecutionPlan,
    guard: ToolLoopGuard,
    run: AgentRun,
    projector: ReadyResultPolicy,
) -> LoopDispatchBinding:
    if not isinstance(run, AgentRun):
        raise AssemblyError()
    return bind_loop_dispatcher(plan, guard, run.context, run.dispatcher, projector)
