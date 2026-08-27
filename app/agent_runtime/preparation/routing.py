"""Resolved-route and turn-decision preparation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable

from ..contracts import ContextStageResult, RoutingStageResult


@dataclass(slots=True)
class RoutingDependencies:
    route_question: Callable[[str], Any]
    recover_active_flow: Callable[[list[dict] | None], str | None]
    arbitrate_decision: Callable[..., Any]
    build_turn_decision: Callable[..., Any]
    intent_labels: set[str]
    notify: Callable[..., Awaitable[None]]
    emit: Callable[..., None]
    perf_counter: Callable[[], float]
    progress_message: Callable[[Any], str]


async def prepare_routing_stage(
    question: str,
    history: list[dict] | None,
    run_id: str,
    progress: Any,
    context: ContextStageResult,
    *,
    deps: RoutingDependencies,
) -> RoutingStageResult:
    started = deps.perf_counter()
    resolution, direct_route = context.resolution, context.direct_route
    analysis_question = resolution.resolved_question
    resolved_route = (
        deps.route_question("介绍一下你自己")
        if resolution.strategy in {"semantic_recall", "context_clarification"}
        else deps.route_question(analysis_question)
        if resolution.applied
        else direct_route
    )
    arbitration = deps.arbitrate_decision(
        original_question=question,
        resolved_question=analysis_question,
        original_route=direct_route,
        resolved_route=resolved_route,
        context=resolution,
        raw_model_actions=list(resolution.turn_actions)
        if resolution.turn_actions
        else None,
        previous_active_flow=deps.recover_active_flow(history),
    )
    intent_route = arbitration.route
    analysis_question = arbitration.effective_question
    if intent_route.intent != resolved_route.intent:
        deps.emit(
            "decision_arbitrated",
            run_id,
            from_intent=resolved_route.intent,
            to_intent=intent_route.intent,
            selected_origin=arbitration.selected_origin,
            policy_reason=arbitration.policy_reason,
        )
    route_payload = intent_route.to_dict()
    decision = deps.build_turn_decision(
        route=intent_route.intent,
        relation=resolution.relation,
        confidence=resolution.confidence,
        question=analysis_question,
        model_actions=[item.to_dict() for item in arbitration.model_actions] or None,
        context_failure_reason=resolution.failure_reason,
        valid_route_intents=deps.intent_labels
        - {"conversation", "unknown", "ambiguous"},
    )
    action = next(
        (
            item
            for item in decision.actions
            if item.type in {"answer_meta", "route_task"}
        ),
        None,
    )
    active_flow = arbitration.active_flow
    if action and action.type == "answer_meta" and action.subject:
        active_flow = f"meta:{action.subject}"
    elif action and action.type == "route_task" and action.target_intent:
        active_flow = f"task:{action.target_intent}"
    decision = replace(
        decision,
        active_flow=active_flow,
        selected_origin=arbitration.selected_origin,
        policy_reason=arbitration.policy_reason,
        candidates=tuple(item.to_dict() for item in arbitration.candidates),
    )
    deps.emit(
        "turn_decision_degraded"
        if (decision.source == "fallback" or decision.failure_reason)
        else "turn_decision_created",
        run_id,
        turn_decision_schema_version=decision.schema_version,
        source=decision.source,
        route=decision.route,
        relation=decision.relation,
        action_types=[item.type for item in decision.actions],
        subjects=[item.subject for item in decision.actions if item.subject],
        detail=[item.detail for item in decision.actions],
        confidence=decision.confidence,
        fallback_reason=decision.failure_reason or None,
        selected_origin=decision.selected_origin,
        active_flow=decision.active_flow,
        policy_reason=decision.policy_reason,
        decision_candidates=list(decision.candidates),
        decision_candidate_count=len(decision.candidates),
        selected_candidate_count=sum(
            item.get("status") == "selected" for item in decision.candidates
        ),
        rejected_candidate_count=sum(
            item.get("status") == "rejected" for item in decision.candidates
        ),
    )
    deps.emit(
        "intent_routed",
        run_id,
        intent=intent_route.intent,
        confidence=intent_route.confidence,
        process_steps=list(intent_route.process_steps),
        equipment_ids=list(intent_route.equipment_ids),
        scope_resolution=route_payload["scope_resolution"],
        time_range=route_payload["time_range"],
        data_requirements=list(intent_route.data_requirements),
        risk_level=intent_route.risk_level,
        clarification_needed=intent_route.clarification_needed,
    )
    await deps.notify(
        progress,
        {
            "event": "stage",
            "stage": "routing",
            "message": deps.progress_message(intent_route),
            "route": route_payload,
        },
    )
    return RoutingStageResult(
        analysis_question,
        intent_route,
        decision,
        started,
    )


def emit_routing_completed(
    run_id: str,
    routing: RoutingStageResult,
    *,
    deps: RoutingDependencies,
) -> None:
    deps.emit(
        "routing_stage_completed",
        run_id,
        status="success",
        intent=routing.intent_route.intent,
        selected_origin=routing.turn_decision.selected_origin,
        policy_reason=routing.turn_decision.policy_reason,
        candidate_count=len(routing.turn_decision.candidates),
        duration_ms=round((deps.perf_counter() - routing.started_monotonic) * 1000, 1),
    )
