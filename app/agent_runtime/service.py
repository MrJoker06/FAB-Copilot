from __future__ import annotations

import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any

from . import AgentRunLifecycle, AgentRunRequest, ProgressCallback, coordinate_agent_run
from .compatibility import (
    AgentCompatibilityFacade,
    _notify,
    _trace_reference_counts,
    content_fingerprint,
    emit,
    install_agent_compatibility_exports,
)

_COMPATIBILITY = AgentCompatibilityFacade(lambda: globals())
install_agent_compatibility_exports(globals(), _COMPATIBILITY)


def _coordinator_dependencies():
    return _COMPATIBILITY.call("_coordinator_dependencies")


async def _run_agent_impl(
    question: str, history: list[dict] | None, run_id: str,
    progress=None, thinking: bool = False,
) -> dict:
    return await coordinate_agent_run(
        AgentRunRequest(question, history, run_id, thinking),
        progress, deps=_coordinator_dependencies(),
    )

async def run_agent(
    question: str,
    history: list[dict] | None = None,
    progress: ProgressCallback | None = None,
    *,
    thinking: bool = False,
    session_id: str | None = None,
    user_message_id: int | None = None,
) -> dict:
    run_id = str(uuid.uuid4())
    lifecycle = AgentRunLifecycle(
        started_monotonic=time.perf_counter(),
        started_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
    )

    async def tracked_progress(event: dict) -> None:
        if event.get("event") == "answer_delta" and lifecycle.first_answer_delta_monotonic is None:
            lifecycle.observe_progress(event, time.perf_counter())
        await _notify(progress, event)
    emit(
        "agent_run_started",
        run_id,
        question_length=len(question),
        question_fingerprint=content_fingerprint(question),
        history_messages=len(history or []),
        session_id=session_id,
        user_message_id=user_message_id,
        thinking_policy={"requested": thinking, "context_effective": False, "answer_effective": False},
        full_content={"question": question, "history": history or []},
    )
    await tracked_progress({"event": "run_started", "run_id": run_id, "message": "分析任务已创建"})
    try:
        result = await _run_agent_impl(
            question,
            history,
            run_id,
            tracked_progress,
            thinking,
        )
        result.setdefault("thinking_policy", {
            "requested": thinking,
            "context_effective": False,
            "answer_effective": False,
        })
        result["run_id"] = run_id
        result["status"] = "success"
        result["started_at"] = lifecycle.started_at
        result["completed_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        result["duration_ms"] = lifecycle.duration_ms(time.perf_counter())
        result["first_token_ms"] = lifecycle.first_token_ms()
        context = result.get("context_resolution") if isinstance(result.get("context_resolution"), dict) else {}
        degraded = context.get("resolution_state") == "unavailable"
        reference_counts = _trace_reference_counts(result)
        tool_trace = result.get("tool_trace") if isinstance(result.get("tool_trace"), list) else []
        retrieval_duration_ms = round(sum(
            float(item.get("duration_ms", 0) or 0)
            for item in tool_trace
            if isinstance(item, dict) and item.get("tool") == "search_knowledge"
        ), 1)
        tool_duration_ms = round(sum(
            float(item.get("duration_ms", 0) or 0)
            for item in tool_trace
            if isinstance(item, dict) and item.get("tool") != "search_knowledge"
        ), 1)
        result["trace_semantics"] = {
            "schema_version": "1.0",
            **reference_counts,
            "retrieval_duration_ms": retrieval_duration_ms,
            "tool_duration_ms": tool_duration_ms,
        }
        emit(
            "agent_run_finished",
            run_id,
            status="success",
            outcome="degraded" if degraded else "completed",
            degraded=degraded,
            degradation_stage="contextualization" if degraded else None,
            degradation_reason=context.get("failure_reason") if degraded else None,
            fallback_action="continue_with_original_question" if degraded else None,
            session_id=session_id,
            user_message_id=user_message_id,
            mode=result.get("mode", "unknown"),
            duration_ms=result["duration_ms"],
            tool_count=len(tool_trace),
            tool_duration_ms=tool_duration_ms,
            retrieval_duration_ms=retrieval_duration_ms,
            **reference_counts,
            # Deprecated compatibility alias: this has always represented the
            # visible knowledge-source cards, not all evidence references.
            source_count=len(result.get("sources", [])),
            intent=result.get("intent_route", {}).get("intent", "unknown"),
            risk_level=result.get("intent_route", {}).get("risk_level", "unknown"),
            playbook_id=(result.get("domain_playbook", {}).get("selected_playbook") or {}).get("playbook_id"),
            playbook_version=(result.get("domain_playbook", {}).get("selected_playbook") or {}).get("playbook_version"),
            plan_id=result.get("execution_plan", {}).get("plan_id"),
            plan_status=result.get("execution_plan", {}).get("status"),
            guard_stop_reason=result.get("loop_guard", {}).get("stop_reason"),
            guard_total_calls=result.get("loop_guard", {}).get("total_calls", 0),
            guard_blocked_calls=result.get("loop_guard", {}).get("blocked_calls", 0),
            guard_unique_evidence_results=result.get("loop_guard", {}).get("unique_evidence_results", 0),
            evidence_required_coverage_pct=result.get("evidence_validation", {}).get("coverage", {}).get("required_coverage_pct", 0),
            evidence_risk_count=len(result.get("evidence_validation", {}).get("risks", [])),
            evidence_conflict_count=len(result.get("evidence_validation", {}).get("conflicts", [])),
            allowed_conclusion_strength=result.get("evidence_validation", {}).get("allowed_conclusion_strength"),
            answer_synthesis_status=result.get("answer_synthesis", {}).get("status"),
            answer_synthesis_moved_claims=result.get("answer_synthesis", {}).get("moved_claims", 0),
            answer_synthesis_invalid_sources=len(result.get("answer_synthesis", {}).get("invalid_source_refs", [])),
            full_content={
                "answer": result.get("answer"),
                "tool_trace": result.get("tool_trace", []),
                "sources": result.get("sources", []),
                "loop_guard": result.get("loop_guard", {}),
                "evidence_validation": result.get("evidence_validation", {}),
                "answer_contract": result.get("answer_contract", {}),
                "answer_synthesis": result.get("answer_synthesis", {}),
            },
        )
        return result
    except Exception as exc:
        await tracked_progress({"event": "run_failed", "run_id": run_id, "message": str(exc)})
        emit(
            "agent_run_finished",
            run_id,
            status="error",
            duration_ms=lifecycle.duration_ms(time.perf_counter()),
            error_type=type(exc).__name__,
            full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
        )
        raise
