"""Explicit assembly checks for dispatcher-backed Ready execution."""

from __future__ import annotations

from ..agent_runtime.application import AgentRun
from ..agent_runtime.execution.loop_guard import ToolLoopGuard
from ..agent_runtime.execution.ready_dispatch import ReadyDispatchBinding
from ..agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from ..agent_runtime.execution.runtime_contracts import RuntimeContext
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.dispatcher import ToolDispatcher
from ..planning_runtime.contracts import ExecutionPlan
from .agent_assembly import AssemblyError


def bind_ready_dispatcher(
    plan: ExecutionPlan,
    guard: ToolLoopGuard,
    context: RuntimeContext,
    dispatcher: ToolDispatcher,
    projector: ReadyResultPolicy,
) -> ReadyDispatchBinding:
    """Bind the exact Guard, Dispatcher and policy instances for one Ready run."""
    if (
        not isinstance(plan, ExecutionPlan)
        or not isinstance(guard, ToolLoopGuard)
        or not isinstance(context, RuntimeContext)
        or not isinstance(dispatcher, ToolDispatcher)
        or not isinstance(projector, ReadyResultPolicy)
        or guard.plan is not plan
        or context.run_id != dispatcher.run_id
        or not isinstance(dispatcher.budget, LoopGuardToolBudget)
        or dispatcher.budget.guard is not guard
        or dispatcher.result_policy is not projector
    ):
        raise AssemblyError()
    return ReadyDispatchBinding(
        plan,
        guard,
        context,
        dispatcher,
        projector.take_raw_rows,
        projector.extract_sources,
        projector.clear,
    )


def bind_ready_run(
    plan: ExecutionPlan,
    guard: ToolLoopGuard,
    run: AgentRun,
    projector: ReadyResultPolicy,
) -> ReadyDispatchBinding:
    """Bind a Ready plan to a run assembled by the native application factory."""
    if not isinstance(run, AgentRun):
        raise AssemblyError()
    return bind_ready_dispatcher(plan, guard, run.context, run.dispatcher, projector)
