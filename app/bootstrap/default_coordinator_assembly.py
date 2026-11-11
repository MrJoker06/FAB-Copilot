"""Default v2 coordinator assembly using named plans and per-run tools."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Mapping

from ..core.identity import current_principal
from app.planning_runtime.named_playbooks import select_named_playbook
from ..planning_runtime.named_planner import create_named_execution_plan
from .legacy_agent_assembly import build_legacy_coordinator_dependencies
from .storage_identity_assembly import install_default_storage_identity

if TYPE_CHECKING:
    from ..agent_runtime.coordinator_state import CoordinatorRunState
    from ..agent_runtime.dependencies import CoordinatorDependencies
    from ..agent_runtime.execution.loop_guard import ToolLoopGuard
    from ..agent_runtime.ports import RuntimeSettings
    from ..agent_runtime.preparation.pipeline import PreparationDependencies
    from ..agent_runtime.synthesis.fallback import PrecomputedTools
    from ..planning_runtime.contracts import ExecutionPlan
    from .default_tool_assembly import DefaultRunTools

# Importing app.agent_runtime.service reaches this module, so direct Python
# callers of run_agent get the same storage/identity bindings as app.main.
install_default_storage_identity()


def build_default_coordinator_dependencies(
    namespace: Mapping[str, Any],
) -> CoordinatorDependencies:
    """Preserve the live compatibility facade while selecting the v2 capability."""
    dependencies = build_legacy_coordinator_dependencies(namespace)
    legacy_factory = dependencies.preparation.agent_preparation_dependencies

    def agent_preparation_dependencies() -> PreparationDependencies:
        group = legacy_factory()
        planning = replace(
            group.planning,
            select_playbook=select_named_playbook,
            create_execution_plan=create_named_execution_plan,
        )
        return replace(group, planning=planning)

    def tool_run_factory(
        *,
        settings: RuntimeSettings,
        plan: ExecutionPlan,
        guard: ToolLoopGuard,
        run_id: str,
    ) -> DefaultRunTools:
        # Import lazily so historical explicit assembly remains importable alone.
        from .default_tool_assembly import build_default_run_tools
        from .tool_bindings import _LEGACY_BINDINGS

        return build_default_run_tools(
            settings=settings,
            principal=current_principal(),
            plan=plan,
            guard=guard,
            run_id=run_id,
            usable_knowledge_result=namespace["_usable_knowledge_result"],
            handlers=namespace["TOOL_HANDLERS"],
            baseline_handlers=_LEGACY_BINDINGS,
        )

    async def offline_tool_runner(
        state: CoordinatorRunState,
    ) -> PrecomputedTools | None:
        from ..agent_runtime.execution.loop_dispatch import (
            execute_dispatched_loop_round,
        )
        from ..agent_runtime.execution.loop_response import LoopResponse, ModelToolCall
        from ..agent_runtime.synthesis.fallback import PrecomputedTools

        deps = dependencies
        # A default native run must never fall through to the historical local
        # callbacks.  Even routes which intentionally select no business reads get
        # an explicit empty native bundle; legacy replay still uses ``None``.
        precomputed_tools = (
            PrecomputedTools(trace=[], observations=[], results={})
            if getattr(getattr(state, "tool_run", None), "loop", None) is not None
            else None
        )
        loop_binding = getattr(getattr(state, "tool_run", None), "loop", None)
        if (
            loop_binding is not None
            and state.intent_route.intent
            not in {
                "general_knowledge",
                "conversation",
                "unknown",
                "ambiguous",
            }
            and state.execution_plan.status != "clarification_required"
        ):
            response = LoopResponse(
                "tools",
                "",
                (
                    ModelToolCall("offline-overview", "get_fab_overview", "{}"),
                    ModelToolCall("offline-equipment", "get_equipment_health", "{}"),
                ),
            )
            outcome = await execute_dispatched_loop_round(
                state.execution_plan,
                state.loop_guard,
                state.run_id,
                1,
                response,
                state.progress,
                binding=loop_binding,
                notify=deps.notify,
                emit_event=deps.emit,
            )
            values: dict[str, object] = {}
            for result_item in outcome.tool_results:
                if result_item.status.value == "succeeded":
                    values[result_item.tool_name] = result_item.data
            precomputed_tools = PrecomputedTools(
                trace=outcome.trace,
                observations=[
                    deps.evidence_observation_type(**item)
                    for item in outcome.observation_payloads
                ],
                results=values,
            )
        return precomputed_tools

    return replace(
        dependencies,
        preparation=replace(
            dependencies.preparation,
            agent_preparation_dependencies=agent_preparation_dependencies,
        ),
        tool_run_factory=tool_run_factory,
        offline_tool_runner=offline_tool_runner,
    )
