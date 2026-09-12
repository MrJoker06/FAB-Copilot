"""Deterministic general-knowledge retrieval behind injected legacy dependencies."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ...evidence.validator import EvidenceObservation
from ...knowledge.decision import RetrievalDecision
from ..execution.loop_guard import ToolLoopGuard


@dataclass(slots=True)
class RetrievalDependencies:
    required_scopes: Callable[[str], tuple[str, ...]]
    rewrite_query: Callable[[str], Any]
    assess_retrieval: Callable[[list[dict[str, Any]], list[dict[str, Any]], Any], RetrievalDecision]
    execute_tool: Callable[[str, dict[str, Any]], Any]
    usable_result: Callable[[str, dict[str, Any]], bool]
    notify: Callable[[Any, dict[str, Any]], Awaitable[None]]
    emit: Callable[..., None]
    perf_counter: Callable[[], float]


def knowledge_fallback_state(
    intent_route: Any,
    observations: list[EvidenceObservation],
    sources: dict[str, dict],
    *,
    model_knowledge_disclosure: str,
) -> dict[str, Any]:
    if intent_route.intent != "sop_lookup" or sources:
        return {"used": False, "reason": None, "disclosure": None}
    attempts = [item for item in observations if item.tool == "search_knowledge"]
    completed_attempts = [item for item in attempts if item.status in {"success", "error"}]
    if not completed_attempts:
        return {"used": False, "reason": None, "disclosure": None}
    successful_empty = any(
        item.status == "success" and item.result in (None, [])
        for item in completed_attempts
    )
    reason = "search_empty" if successful_empty else "search_unavailable"
    disclosure = (
        model_knowledge_disclosure
        if successful_empty
        else "知识库检索未获得可用内容。以下回答使用模型通用知识，仅供参考，不代表厂内 SOP、规格或当前生产事实。"
    )
    return {"used": True, "reason": reason, "disclosure": disclosure}


def usable_knowledge_result(query: str, result: dict[str, Any], *, usable_result: Callable[[str, dict[str, Any]], bool]) -> bool:
    return usable_result(query, result)


def normalize_general_knowledge_answer(answer: str) -> str:
    stripped = answer.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else stripped
    try:
        payload = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return answer
    if not isinstance(payload, dict):
        return answer
    tool_calls = payload.get("tool_calls")
    if not isinstance(tool_calls, list):
        return answer
    for call in tool_calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or function.get("name") != "submit_analysis":
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if not isinstance(arguments, dict):
            continue
        content = arguments.get("content") or arguments.get("answer")
        if isinstance(content, str) and content.strip():
            return content.strip()
        conclusion = arguments.get("conclusion")
        if isinstance(conclusion, str) and conclusion.strip():
            return conclusion.strip()
    return answer


def has_knowledge_fallback_disclosure(answer: str) -> bool:
    compact = re.sub(r"\s+", "", answer).lower()
    return bool(
        "个人知识库" in compact
        and "工厂知识库" in compact
        and any(term in compact for term in ("未检索到", "没有检索到", "无可用"))
        and any(term in compact for term in ("模型通用知识", "通用知识", "仅供参考"))
    )


async def prefetch_general_knowledge(
    question: str,
    run_id: str,
    loop_guard: ToolLoopGuard,
    observations: list[EvidenceObservation],
    trace: list[dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    progress: Any,
    *,
    deps: RetrievalDependencies,
) -> RetrievalDecision:
    retrieval_started = deps.perf_counter()
    attempts: list[dict[str, Any]] = []
    scopes = deps.required_scopes(question)
    rewrite = deps.rewrite_query(question)
    queries = [("original", question)]
    if rewrite.changed:
        queries.append(("rewritten", rewrite.query))

    for query_variant, query in queries:
        loop_guard.begin_round()
        for scope in scopes:
            arguments = {"query": query, "limit": 10, "source_types": [scope]}
            tool_started = deps.perf_counter()
            await deps.notify(progress, {
                "event": "tool_started", "tool": "search_knowledge", "arguments": arguments,
                "scope": scope, "query_variant": query_variant,
            })
            deps.emit(
                "tool_call_started", run_id, tool="search_knowledge",
                tool_call_id=f"prefetch-{query_variant}-{scope}", retrieval_scope=scope,
                query_variant=query_variant, full_content={"arguments": arguments},
            )
            guard_decision = loop_guard.check_call("search_knowledge", arguments)
            if not guard_decision.allowed:
                duration_ms = round((deps.perf_counter() - tool_started) * 1000, 1)
                attempts.append({
                    "scope": scope, "query_variant": query_variant, "query": query,
                    "status": "blocked", "raw_count": 0, "usable_count": 0,
                    "error_code": guard_decision.reason_code,
                })
                observations.append(EvidenceObservation(
                    "search_knowledge", arguments, "blocked", error=guard_decision.message
                ))
                item = {
                    "tool": "search_knowledge", "arguments": arguments, "status": "blocked",
                    "rows": 0, "error_code": guard_decision.reason_code,
                    "error": guard_decision.message, "duration_ms": duration_ms,
                    "retrieval_scope": scope, "query_variant": query_variant,
                }
                trace.append(item)
                await deps.notify(progress, {"event": "tool_finished", **item})
                continue
            try:
                result = deps.execute_tool("search_knowledge", arguments)
                raw_count = len(result) if isinstance(result, list) else 0
                usable = [
                    item for item in result
                    if isinstance(item, dict) and deps.usable_result(query, item)
                ] if isinstance(result, list) else []
                for source in usable:
                    sources[str(source["reference_id"])] = source
                loop_guard.record_result("search_knowledge", usable, True)
                observations.append(EvidenceObservation("search_knowledge", arguments, "success", usable))
                duration_ms = round((deps.perf_counter() - tool_started) * 1000, 1)
                attempts.append({
                    "scope": scope, "query_variant": query_variant, "query": query,
                    "status": "success", "raw_count": raw_count, "usable_count": len(usable),
                    "reference_ids": [str(item.get("reference_id")) for item in usable],
                })
                trace_item = {
                    "tool": "search_knowledge", "arguments": arguments, "status": "ok",
                    "rows": len(usable), "raw_rows": raw_count, "duration_ms": duration_ms,
                    "retrieval_scope": scope, "query_variant": query_variant,
                }
                trace.append(trace_item)
                await deps.notify(progress, {"event": "tool_finished", **trace_item})
                deps.emit(
                    "tool_call_finished", run_id, status="success", tool="search_knowledge",
                    duration_ms=duration_ms, retrieval_scope=scope, query_variant=query_variant,
                    raw_rows=raw_count, rows=len(usable), full_content={"result": usable},
                )
            except Exception as exc:
                loop_guard.record_result("search_knowledge", None, False)
                observations.append(EvidenceObservation("search_knowledge", arguments, "error", error=str(exc)))
                duration_ms = round((deps.perf_counter() - tool_started) * 1000, 1)
                attempts.append({
                    "scope": scope, "query_variant": query_variant, "query": query,
                    "status": "error", "raw_count": 0, "usable_count": 0,
                    "error_type": type(exc).__name__,
                })
                trace_item = {
                    "tool": "search_knowledge", "arguments": arguments, "status": "error",
                    "rows": 0, "error": str(exc), "duration_ms": duration_ms,
                    "retrieval_scope": scope, "query_variant": query_variant,
                }
                trace.append(trace_item)
                await deps.notify(progress, {"event": "tool_finished", **trace_item})
                deps.emit(
                    "tool_call_finished", run_id, status="error", tool="search_knowledge",
                    duration_ms=duration_ms, retrieval_scope=scope, query_variant=query_variant,
                    error_type=type(exc).__name__, full_content={"error_message": str(exc)},
                )
        loop_guard.finish_round()

    decision = deps.assess_retrieval(attempts, list(sources.values()), rewrite)
    decision_payload = decision.to_dict()
    deps.emit(
        "knowledge_retrieval_decided", run_id, state=decision.state, reason=decision.reason,
        attempted_scopes=list(decision.attempted_scopes), source_counts=decision.source_counts,
        rewritten=bool(decision.rewritten_query), model_knowledge_allowed=decision.model_knowledge_allowed,
        duration_ms=round((deps.perf_counter() - retrieval_started) * 1000, 1),
        full_content={"retrieval_decision": decision_payload},
    )
    await deps.notify(progress, {
        "event": "stage", "stage": "knowledge_retrieval",
        "message": (
            f"知识检索完成 · 个人 {decision.source_counts['personal']} · "
            f"工厂 {decision.source_counts['knowledge']} · 案例 {decision.source_counts['case']}"
        ),
        "retrieval_decision": decision_payload,
    })
    return decision
