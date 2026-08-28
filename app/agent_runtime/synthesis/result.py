"""Final answer result assembly for normal and deterministic-ready paths."""

from __future__ import annotations

from typing import Any


def not_applicable_retrieval_decision() -> dict[str, Any]:
    """Return the stable retrieval payload used when retrieval was not attempted."""
    return {
        "state": "NOT_APPLICABLE",
        "reason": None,
        "attempted_scopes": [],
        "attempts": [],
        "selected_reference_ids": [],
        "source_counts": {"personal": 0, "knowledge": 0, "case": 0},
        "rewritten_query": None,
        "assumptions": [],
        "model_knowledge_allowed": False,
        "disclosure": None,
    }


def build_result(
    answer: str,
    synthesis_report: Any,
    *,
    trace: list[dict],
    sources: dict[str, dict],
    intent_route: Any,
    connection: Any,
    total_usage: dict[str, int],
    route_payload: dict,
    playbook_payload: dict,
    plan_payload: dict,
    loop_guard: Any,
    evidence_validation: Any,
    answer_contract: Any,
    context_resolution: Any,
    knowledge_fallback: dict,
    retrieval_decision_payload: dict,
    thinking: bool,
    thinking_answer_effective: bool,
    turn_decision: Any,
) -> dict:
    """Build the normal model result using the state visible at invocation time."""
    cited_references = {
        reference
        for reference in synthesis_report.source_refs
        if not reference.startswith("TOOL:")
    }
    if intent_route.intent == "general_knowledge":
        cited_references.update(retrieval_decision_payload["selected_reference_ids"])
    return {
        "answer": answer,
        "tool_trace": trace,
        "sources": [
            source
            for reference, source in sources.items()
            if reference in cited_references
        ],
        "mode": "deepseek",
        "model": connection.model,
        "usage": total_usage,
        "intent_route": route_payload,
        "domain_playbook": playbook_payload,
        "execution_plan": plan_payload,
        "loop_guard": loop_guard.summary(),
        "evidence_validation": evidence_validation.to_dict(),
        "answer_contract": answer_contract.to_dict(),
        "answer_synthesis": synthesis_report.to_dict(),
        "context_resolution": context_resolution.to_dict(),
        "knowledge_fallback": knowledge_fallback,
        "retrieval_decision": retrieval_decision_payload,
        "thinking_policy": {
            "requested": thinking,
            "context_effective": False,
            "answer_effective": thinking_answer_effective,
        },
        "turn_decision": turn_decision.to_dict(),
    }


def build_ready_model_unavailable_result(
    answer: str,
    synthesis_report: Any,
    *,
    trace: list[dict],
    route_payload: dict,
    playbook_payload: dict,
    plan_payload: dict,
    loop_guard: Any,
    evidence_validation: Any,
    answer_contract: Any,
    context_resolution: Any,
    thinking: bool,
    turn_decision: Any,
    selected_model_id: str,
    fallback_reason: str,
    model_health: dict[str, Any],
    usage: dict[str, int],
) -> dict:
    """Build the complete ready-plan response when a model request is unavailable."""
    return {
        "answer": answer,
        "tool_trace": trace,
        "sources": [],
        "mode": "deterministic-fallback",
        "model": "local-rules",
        "usage": usage,
        "intent_route": route_payload,
        "domain_playbook": playbook_payload,
        "execution_plan": plan_payload,
        "loop_guard": loop_guard.summary(),
        "evidence_validation": evidence_validation.to_dict(),
        "answer_contract": answer_contract.to_dict(),
        "answer_synthesis": synthesis_report.to_dict(),
        "context_resolution": context_resolution.to_dict(),
        "knowledge_fallback": {"used": False, "reason": None, "disclosure": None},
        "retrieval_decision": not_applicable_retrieval_decision(),
        "thinking_policy": {
            "requested": thinking,
            "context_effective": False,
            "answer_effective": False,
        },
        "turn_decision": turn_decision.to_dict(),
        "model_health": {
            "requested_model_id": selected_model_id,
            "fallback_reason": fallback_reason,
            **model_health,
        },
        "execution_mode": "deterministic_ready_plan",
        "model_tool_selection_calls": 0,
    }
