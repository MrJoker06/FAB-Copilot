"""Domain-playbook selection and execution-plan preparation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..contracts import PlanningStageResult


@dataclass(slots=True)
class PlanningDependencies:
    select_playbook: Callable[[Any], Any]
    create_execution_plan: Callable[[str, Any, Any], Any]
    notify: Callable[..., Awaitable[None]]
    emit: Callable[..., None]
    playbook_message: Callable[[Any], str]
    plan_message: Callable[[Any], str]


async def prepare_planning_stage(
    question: str, route: Any, run_id: str, progress: Any, *, deps: PlanningDependencies
) -> PlanningStageResult:
    selection = deps.select_playbook(route)
    playbook_payload = selection.to_dict()
    selected = selection.selected_playbook
    deps.emit(
        "playbook_selected",
        run_id,
        status=selection.status,
        route_intent=route.intent,
        playbook_id=selected.playbook_id if selected else None,
        playbook_version=selected.playbook_version if selected else None,
        candidate_playbooks=[
            item.playbook_id for item in selection.candidate_playbooks
        ],
    )
    await deps.notify(
        progress,
        {
            "event": "stage",
            "stage": "playbook",
            "message": deps.playbook_message(selection),
            "playbook": playbook_payload,
        },
    )
    plan = deps.create_execution_plan(question, route, selection)
    plan_payload = plan.to_dict()
    deps.emit(
        "execution_plan_created",
        run_id,
        plan_id=plan.plan_id,
        status=plan.status,
        planner_version=plan.planner_version,
        playbook_id=plan.playbook_id,
        playbook_version=plan.playbook_version,
        primary_scope_type=plan.scope_contract.primary_scope_type,
        primary_scope_ids=list(plan.scope_contract.primary_scope_ids),
        context_only_tools=list(plan.scope_contract.context_only_tools),
        step_count=len(plan.steps),
        required_evidence_count=len(plan.required_evidence_ids),
        planned_tool_calls=plan.budget.planned_tool_calls,
        max_tool_calls=plan.budget.max_tool_calls,
        missing_inputs=list(plan.missing_inputs),
    )
    return PlanningStageResult(selection, playbook_payload, plan, plan_payload)


async def emit_plan_progress(
    progress: Any,
    planning: PlanningStageResult,
    *,
    deps: PlanningDependencies,
) -> None:
    await deps.notify(
        progress,
        {
            "event": "stage",
            "stage": "plan",
            "message": deps.plan_message(planning.execution_plan),
            "plan": planning.plan_payload,
        },
    )
