"""Single, provenance-aware authority for the turn's final route.

The contextualizer may expand a follow-up for readability, but expansion is
parameter context rather than a new user request.  This module keeps that
boundary explicit before the existing Router/Planner path begins.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from ..memory_system.contracts import ContextResolution
from ..intent_runtime import INTENT_LABELS, IntentRoute, apply_semantic_intent_hint, route_question
from .turn_decision import TurnAction, TurnDecisionValidationError, validate_turn_actions


_META_SUBJECTS = {
    "identity", "capabilities", "usage_help", "limitations_policy",
    "runtime_status", "response_review", "social", "other",
}
_TASK_INTENTS = set(INTENT_LABELS) - {"conversation", "unknown", "ambiguous"}
_EXPLICIT_TASK_INTENTS = _TASK_INTENTS


@dataclass(frozen=True)
class DecisionCandidate:
    kind: str
    value: str
    origin: str
    confidence: float
    status: str = "rejected"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "value": self.value,
            "origin": self.origin,
            "confidence": round(self.confidence, 2),
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ArbitrationResult:
    route: IntentRoute
    effective_question: str
    model_actions: tuple[TurnAction, ...]
    active_flow: str | None
    selected_origin: str
    policy_reason: str
    candidates: tuple[DecisionCandidate, ...]


def recover_active_flow(history: Iterable[dict] | None) -> str | None:
    """Restore only a constrained field from the last assistant metadata."""
    for message in reversed(list(history or ())):
        if message.get("role") != "assistant":
            continue
        metadata = message.get("metadata")
        decision = metadata.get("turn_decision") if isinstance(metadata, dict) else None
        value = decision.get("active_flow") if isinstance(decision, dict) else None
        if not isinstance(value, str):
            return None
        if value.startswith("meta:") and value.removeprefix("meta:") in _META_SUBJECTS:
            return value
        if value.startswith("task:") and value.removeprefix("task:") in _TASK_INTENTS:
            return value
        return None
    return None


def _conversation_route(confidence: float) -> IntentRoute:
    route = route_question("介绍一下你自己")
    return replace(route, confidence=round(min(max(confidence, 0.65), 0.95), 2))


def _valid_meta_actions(raw_actions: object) -> tuple[TurnAction, ...]:
    if raw_actions is None:
        return ()
    try:
        actions = validate_turn_actions(raw_actions, allowed_route_intents=_TASK_INTENTS)
    except TurnDecisionValidationError:
        return ()
    return tuple(item for item in actions if item.type in {"answer_meta", "acknowledge"})


def _flow_for(route: IntentRoute, actions: tuple[TurnAction, ...], previous: str | None) -> str | None:
    meta = next((item for item in actions if item.type == "answer_meta" and item.subject), None)
    if meta:
        return f"meta:{meta.subject}"
    if route.intent in _TASK_INTENTS:
        return f"task:{route.intent}"
    return previous


def arbitrate_decision(
    *,
    original_question: str,
    resolved_question: str,
    original_route: IntentRoute,
    resolved_route: IntentRoute,
    context: ContextResolution,
    raw_model_actions: object = None,
    previous_active_flow: str | None = None,
) -> ArbitrationResult:
    """Choose one final route with a small, auditable policy surface."""
    original = apply_semantic_intent_hint(original_route, context.intent_hint, context.confidence)
    resolved = apply_semantic_intent_hint(
        resolved_route, context.intent_hint, context.confidence, context_applied=context.applied,
    )
    actions = _valid_meta_actions(raw_model_actions)
    meta_action = next((item for item in actions if item.type == "answer_meta"), None)
    candidates = [
        DecisionCandidate("route", original.intent, "original_text", original.confidence),
        DecisionCandidate("route", resolved.intent, "model_expansion", resolved.confidence),
    ]
    if meta_action:
        candidates.append(DecisionCandidate("action", f"answer_meta:{meta_action.subject}", "semantic_context", context.confidence))

    # Recall and the deterministic UI option resolver already have constrained
    # provenance; keep their historical behavior without asking expansion to
    # prove a new task again.
    if context.strategy == "semantic_recall":
        selected = _conversation_route(context.confidence)
        origin, reason, accepted = "semantic_context", "trusted_semantic_recall", ()
    # Keep the pre-existing source-preference correction. It must be evaluated
    # before an otherwise source-word-driven `sop_lookup` original candidate,
    # but never over an explicit manufacturing task in original text.
    elif (
        context.applied
        and context.intent_hint == "general_knowledge"
        and context.confidence >= 0.65
        and resolved.intent == "general_knowledge"
        and original.intent in {"unknown", "sop_lookup"}
    ):
        selected = resolved
        origin, reason, accepted = "model_expansion", "general_knowledge_context_preference", ()
    # A complete task in the user's literal input always starts/switches task
    # flow.  It is the protection against stale meta Flow hijacking a request.
    elif original.intent in _EXPLICIT_TASK_INTENTS:
        selected = original
        origin, reason, accepted = "original_text", "explicit_original_task", ()
    elif (
        context.applied
        and context.relation in {"followup", "correction"}
        and context.confidence >= 0.65
        and resolved.intent in _TASK_INTENTS
        and previous_active_flow == f"task:{resolved.intent}"
    ):
        selected = resolved
        origin, reason, accepted = "model_expansion", "active_task_flow_continuation", ()
    elif context.strategy == "context_clarification":
        selected = _conversation_route(context.confidence)
        origin, reason, accepted = "semantic_context", "trusted_context_clarification", ()
    elif context.source == "deterministic" and context.applied:
        selected = resolved
        origin, reason, accepted = "history", "deterministic_context_selection", ()
    elif (
        context.relation in {"followup", "correction"}
        and context.confidence >= 0.65
        and meta_action is not None
        and previous_active_flow is not None
        and previous_active_flow.startswith("meta:")
    ):
        selected = _conversation_route(context.confidence)
        origin, reason, accepted = "semantic_context", "active_meta_flow_continuation", actions
    elif original.intent == "conversation":
        selected = original
        origin, reason, accepted = "original_text", "explicit_original_meta", actions
    elif (
        original.intent == "unknown"
        and context.applied
        and context.confidence >= 0.65
        and resolved.intent == "general_knowledge"
    ):
        selected = resolved
        origin, reason, accepted = "model_expansion", "resolved_general_followup", ()
    elif context.relation == "standalone" and resolved.intent in _EXPLICIT_TASK_INTENTS:
        # Defensive fallback: an independently complete contextualizer result
        # is still a task only when it is explicitly marked standalone.
        selected = resolved
        origin, reason, accepted = "model_expansion", "standalone_resolved_task", ()
    elif original.intent in {"unknown", "ambiguous"} and resolved.intent in {"unknown", "ambiguous"}:
        selected = original
        origin, reason, accepted = "original_text", "insufficient_reliable_signal_clarify", ()
    else:
        # A low-confidence follow-up cannot silently activate a task mentioned
        # only by expansion.  Keep the original conservative route.
        selected = original
        origin, reason, accepted = "original_text", "expansion_not_authoritative", ()

    selected_candidates: list[DecisionCandidate] = []
    selected_value = selected.intent
    for candidate in candidates:
        is_selected = candidate.kind == "route" and candidate.value == selected_value and candidate.origin == origin
        if candidate.kind == "action" and accepted and candidate.value.startswith("answer_meta:"):
            is_selected = True
        selected_candidates.append(replace(candidate, status="selected" if is_selected else "rejected", reason=reason if is_selected else "lower_priority_or_guard"))
    if not any(item.status == "selected" for item in selected_candidates):
        selected_candidates.append(
            DecisionCandidate("route", selected.intent, origin, selected.confidence, "selected", reason)
        )
    use_resolved = reason in {
        "trusted_semantic_recall",
        "general_knowledge_context_preference",
        "active_task_flow_continuation",
        "deterministic_context_selection",
        "active_meta_flow_continuation",
        "resolved_general_followup",
        "standalone_resolved_task",
    }
    return ArbitrationResult(
        route=selected,
        effective_question=resolved_question if use_resolved else original_question,
        model_actions=accepted,
        active_flow=_flow_for(selected, accepted, previous_active_flow),
        selected_origin=origin,
        policy_reason=reason,
        candidates=tuple(selected_candidates),
    )
