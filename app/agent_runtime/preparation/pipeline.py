"""Composition root for pre-tool Agent preparation stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contracts import PreparationResult
from .context import ContextStageDependencies, prepare_context_stage
from .planning import PlanningDependencies, emit_plan_progress, prepare_planning_stage
from .routing import (
    RoutingDependencies,
    emit_routing_completed,
    prepare_routing_stage,
)


@dataclass(slots=True)
class PreparationDependencies:
    context: ContextStageDependencies
    routing: RoutingDependencies
    planning: PlanningDependencies


async def prepare_agent_run(
    question: str,
    history: list[dict] | None,
    settings: Any,
    run_id: str,
    progress: Any,
    thinking: bool,
    context_started: float,
    *,
    deps: PreparationDependencies,
) -> PreparationResult:
    context = await prepare_context_stage(
        question,
        history,
        settings,
        run_id,
        progress,
        thinking,
        context_started,
        deps=deps.context,
    )
    routing = await prepare_routing_stage(
        question, history, run_id, progress, context, deps=deps.routing
    )
    planning = await prepare_planning_stage(
        routing.analysis_question,
        routing.intent_route,
        run_id,
        progress,
        deps=deps.planning,
    )
    emit_routing_completed(run_id, routing, deps=deps.routing)
    await emit_plan_progress(progress, planning, deps=deps.planning)
    return PreparationResult(context, routing, planning)
