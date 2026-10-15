"""Preparation and immediate-return stages for one Agent run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..coordinator_state import CoordinatorRunState

if TYPE_CHECKING:
    from ..dependencies import CoordinatorDependencies


@dataclass(frozen=True)
class PrepareImmediateOutcome:
    state: CoordinatorRunState
    result: dict | None = None


async def prepare_immediate(
    state: CoordinatorRunState,
    *,
    deps: CoordinatorDependencies,
) -> PrepareImmediateOutcome:
    """Prepare a run and return deterministic clarification/conversation results."""

    state.settings = deps.effective_agent_settings(deps.get_settings())
    state.preparation = await deps.prepare_agent_run(
        state.question,
        state.history,
        state.settings,
        state.run_id,
        state.progress,
        state.thinking,
        deps.perf_counter(),
        deps=deps.agent_preparation_dependencies(),
    )
    context = state.preparation.context
    routing = state.preparation.routing
    planning = state.preparation.planning
    state.context_resolution = context.resolution
    state.context_usage = context.usage
    state.health_enabled = isinstance(state.settings, deps.settings_type)
    state.selected_model_id = context.selected_model_id
    state.analysis_question = routing.analysis_question
    state.intent_route = routing.intent_route
    state.turn_decision = routing.turn_decision
    state.route_payload = state.intent_route.to_dict()
    state.playbook_selection = planning.playbook_selection
    state.playbook_payload = planning.playbook_payload
    state.selected_playbook = state.playbook_selection.selected_playbook
    state.execution_plan = planning.execution_plan
    state.plan_payload = planning.plan_payload
    state.loop_guard = deps.tool_loop_guard_type(state.execution_plan)
    state.evidence_validation = deps.validate_evidence(
        state.execution_plan, state.selected_playbook, state.evidence_observations,
    )
    state.answer_contract = deps.create_answer_contract(
        state.evidence_validation, question=state.question,
        resolved_question=state.analysis_question,
    )
    deps.emit(
        "loop_guard_initialized",
        state.run_id,
        plan_id=state.execution_plan.plan_id,
        max_tool_calls=state.execution_plan.budget.max_tool_calls,
        max_model_iterations=state.execution_plan.budget.max_model_iterations,
        per_tool_limits=state.execution_plan.budget.per_tool_limits,
        max_identical_parameter_calls=state.execution_plan.budget.max_identical_parameter_calls,
        max_no_progress_rounds=state.execution_plan.budget.max_no_progress_rounds,
    )
    if state.execution_plan.status == "clarification_required":
        await deps.notify(state.progress, {
            "event": "stage", "stage": "clarification",
            "message": "当前分析目标仍不明确，正在整理需要补充的信息",
        })
        result = _immediate_answer(state, deps)
        result["mode"] = "clarification"
        return PrepareImmediateOutcome(state, result)
    if state.intent_route.intent == "conversation":
        result = _immediate_answer(state, deps)
        result["knowledge_fallback"] = {"used": False, "reason": None, "disclosure": None}
        result["retrieval_decision"] = {
            "state": "NOT_APPLICABLE", "reason": None, "attempted_scopes": [], "attempts": [],
            "selected_reference_ids": [], "source_counts": {"personal": 0, "knowledge": 0, "case": 0},
            "rewritten_query": None, "assumptions": [], "model_knowledge_allowed": False,
            "disclosure": None,
        }
        return PrepareImmediateOutcome(state, result)
    return PrepareImmediateOutcome(state)


def _immediate_answer(state: CoordinatorRunState, deps: CoordinatorDependencies) -> dict:
    result = deps.offline_answer(
        state.analysis_question, state.intent_route, state.playbook_selection,
        state.execution_plan, state.loop_guard, state.context_resolution,
        state.turn_decision,
        {
            "thinking_requested": state.thinking,
            "previous_metadata": next((
                item.get("metadata") for item in reversed(state.history or [])
                if item.get("role") == "assistant" and isinstance(item.get("metadata"), dict)
            ), None),
        },
        state.run_id,
    )
    result["model"] = state.settings.model_connection.model if state.context_usage else "deterministic-router"
    result["usage"] = state.context_usage
    result["context_resolution"] = state.context_resolution.to_dict()
    deps.emit_evidence_validation(state.run_id, 1, result["evidence_validation"])
    deps.emit(
        "answer_synthesis_completed",
        state.run_id,
        plan_id=result["answer_synthesis"]["plan_id"],
        status=result["answer_synthesis"]["status"],
        allowed_conclusion_strength=result["answer_synthesis"]["allowed_conclusion_strength"],
        source_count=0, invalid_source_count=0, moved_claims=0, wording_adjustment_count=0,
    )
    return result
