from __future__ import annotations

import asyncio
import json
import time
import traceback
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from .failure import decide_model_failure


@dataclass
class AgentLoopContext:
    settings: Any
    connection: Any
    intent_route: Any
    execution_plan: Any
    selected_playbook: Any
    loop_guard: Any
    run_id: str
    progress: Any
    thinking: bool
    main_recovery_trial: bool
    health_enabled: bool
    selected_model_id: str
    question: str
    analysis_question: str
    playbook_selection: Any
    context_resolution: Any
    messages: list[dict]
    trace: list[dict]
    sources: dict[str, dict]
    evidence_observations: list[Any]
    evidence_validation: Any
    answer_contract: Any
    total_usage: dict[str, int]
    knowledge_fallback: dict[str, Any]
    fallback_announced: bool
    applied_synthesis_reason: str | None
    health: dict[str, Any]
    build_result: Callable[[str, Any], dict]
    notify: Callable[[Any, dict], Awaitable[None]]
    stream_answer: Callable[[Any, str], Awaitable[None]]
    emit_event: Callable[..., None]
    stream_completion: Callable[..., Awaitable[tuple[dict, dict, str | None]]]
    retryable_model_error: Callable[[Exception], bool]
    model_error_category: Callable[[Exception], str]
    model_failure_reason: Callable[[Exception], str]
    model_retry_delay: Callable[[float, int, Exception], float]
    record_model_success: Callable[[str], tuple[dict, str | None]]
    record_model_failure: Callable[..., tuple[dict, str | None]]
    audit_assistant: Callable[[dict], dict]
    tools: list[dict]
    submit_analysis_tool: dict
    parse_tool_arguments: Callable[[str], tuple[dict, Exception | None]]
    execute_tool: Callable[[str, dict], Any]
    usable_knowledge_result: Callable[[str, dict], bool]
    normalize_general_knowledge_answer: Callable[[str], str]
    has_knowledge_fallback_disclosure: Callable[[str], bool]
    knowledge_fallback_state: Callable[[Any, list[Any], dict[str, dict]], dict]
    validate_evidence: Callable[[Any, Any, list[Any]], Any]
    create_answer_contract: Callable[..., Any]
    validator_system_message: Callable[[Any], str]
    synthesizer_system_message: Callable[[Any], str]
    synthesize_legacy_answer: Callable[..., Any]
    synthesize_submission: Callable[..., Any]
    emit_answer_synthesis: Callable[[str, Any], None]
    emit_evidence_validation: Callable[[str, int, dict[str, Any]], None]
    offline_answer: Callable[..., dict]
    evidence_observation_type: Any
    provider_request_options: Callable[[str, bool], dict]


async def run_agent_loop(context: AgentLoopContext) -> dict:
    """Run the non-ready model/tool loop with live dependencies injected by app.agent_runtime.service."""
    settings = context.settings
    connection = context.connection
    intent_route = context.intent_route
    execution_plan = context.execution_plan
    selected_playbook = context.selected_playbook
    loop_guard = context.loop_guard
    run_id = context.run_id
    progress = context.progress
    thinking = context.thinking
    main_recovery_trial = context.main_recovery_trial
    health_enabled = context.health_enabled
    selected_model_id = context.selected_model_id
    question = context.question
    analysis_question = context.analysis_question
    playbook_selection = context.playbook_selection
    context_resolution = context.context_resolution
    messages = context.messages
    trace = context.trace
    sources = context.sources
    evidence_observations = context.evidence_observations
    evidence_validation = context.evidence_validation
    answer_contract = context.answer_contract
    total_usage = context.total_usage
    knowledge_fallback = context.knowledge_fallback
    fallback_announced = context.fallback_announced
    applied_synthesis_reason = context.applied_synthesis_reason
    health = context.health
    build_result = context.build_result
    _notify = context.notify
    _stream_answer = context.stream_answer
    emit = context.emit_event
    _stream_completion = context.stream_completion
    _retryable_model_error = context.retryable_model_error
    _model_error_category = context.model_error_category
    _model_failure_reason = context.model_failure_reason
    _model_retry_delay = context.model_retry_delay
    record_model_success = context.record_model_success
    record_model_failure = context.record_model_failure
    _audit_assistant = context.audit_assistant
    TOOLS = context.tools
    SUBMIT_ANALYSIS_TOOL = context.submit_analysis_tool
    _parse_tool_arguments = context.parse_tool_arguments
    _execute_registered_tool = context.execute_tool
    _usable_knowledge_result = context.usable_knowledge_result
    _normalize_general_knowledge_answer = context.normalize_general_knowledge_answer
    _has_knowledge_fallback_disclosure = context.has_knowledge_fallback_disclosure
    _knowledge_fallback_state = context.knowledge_fallback_state
    validate_evidence = context.validate_evidence
    create_answer_contract = context.create_answer_contract
    validator_system_message = context.validator_system_message
    synthesizer_system_message = context.synthesizer_system_message
    synthesize_legacy_answer = context.synthesize_legacy_answer
    synthesize_submission = context.synthesize_submission
    _emit_answer_synthesis = context.emit_answer_synthesis
    _emit_evidence_validation = context.emit_evidence_validation
    _offline_answer = context.offline_answer
    EvidenceObservation = context.evidence_observation_type
    provider_request_options = context.provider_request_options
    endpoint = f"{connection.base_url}/chat/completions"
    thinking_answer_effective = False

    def _build_result(answer: str, report: Any) -> dict:
        result = build_result(answer, report)
        result["thinking_policy"]["answer_effective"] = thinking_answer_effective
        return result

    async with httpx.AsyncClient(timeout=settings.api_timeout_seconds) as client:
        for iteration in range(loop_guard.max_model_iterations):
            if iteration == loop_guard.max_model_iterations - 1 and loop_guard.total_calls > 0:
                loop_guard.reserve_final_iteration()
            synthesis_only = loop_guard.force_synthesis
            if synthesis_only and applied_synthesis_reason != loop_guard.stop_reason:
                messages.append({"role": "system", "content": loop_guard.synthesis_instruction()})
                applied_synthesis_reason = loop_guard.stop_reason
            await _notify(progress, {
                "event": "stage",
                "stage": "synthesis" if synthesis_only else "planning",
                "iteration": iteration + 1,
                "message": (
                    f"工具执行已停止，正在基于现有证据组织结论 · {loop_guard.stop_message}"
                    if synthesis_only
                    else "正在理解问题并规划分析路径"
                    if iteration == 0
                    else "正在结合工具结果判断是否继续，并组织结论"
                ),
            })
            request_payload = {
                "model": connection.model,
                "messages": messages,
                "temperature": 0.15,
                **provider_request_options(connection.provider, thinking),
            }
            if intent_route.intent not in {"general_knowledge", "conversation"}:
                request_payload["tools"] = (
                    [SUBMIT_ANALYSIS_TOOL]
                    if synthesis_only and answer_contract.status == "required"
                    else TOOLS
                )
                if not (connection.provider == "deepseek" and thinking):
                    request_payload["tool_choice"] = (
                        "none" if synthesis_only and answer_contract.status != "required" else "auto"
                    )
                if synthesis_only and answer_contract.status == "required":
                    request_payload["max_tokens"] = 8192
            retry_budget = 0 if main_recovery_trial else settings.model_max_retries
            for attempt in range(1, retry_budget + 2):
                model_started = time.perf_counter()
                emit(
                    "model_call_started",
                    run_id,
                    phase="agent_loop",
                    iteration=iteration + 1,
                    attempt=attempt,
                    model=connection.model,
                    message_count=len(messages),
                    thinking_requested=thinking,
                    thinking_effective=thinking,
                    reasoning_effort=request_payload.get("reasoning_effort"),
                    full_content={"request": request_payload},
                )
                stream_state = {
                    "answer_emitted": False,
                    "suppress_embedded_tool_json": intent_route.intent == "general_knowledge",
                    "required_disclosure": knowledge_fallback.get("disclosure") or "",
                }
                try:
                    assistant, usage, response_id = await _stream_completion(
                        client,
                        endpoint,
                        {"Authorization": f"Bearer {connection.api_key}", "Content-Type": "application/json"},
                        request_payload,
                        None if answer_contract.status == "required" else progress,
                        stream_state,
                    )
                except Exception as exc:
                    failure_decision = decide_model_failure(
                        availability_failure=_retryable_model_error(exc),
                        answer_emitted=stream_state["answer_emitted"],
                        attempt=attempt,
                        retry_budget=retry_budget,
                    )
                    availability_failure = failure_decision.availability_failure
                    retryable = failure_decision.retryable
                    will_retry = failure_decision.will_retry
                    emit(
                        "model_call_finished",
                        run_id,
                        status="error",
                        iteration=iteration + 1,
                        attempt=attempt,
                        model=connection.model,
                        duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
                        error_type=type(exc).__name__,
                        phase="agent_loop",
                        retryable=retryable,
                        will_retry=will_retry,
                        answer_emitted=stream_state["answer_emitted"],
                        content_length=int(stream_state.get("content_chars", 0)),
                        thinking_requested=thinking,
                        thinking_effective=thinking,
                        reasoning_effort=request_payload.get("reasoning_effort"),
                        failure_reason=_model_failure_reason(exc),
                        full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
                    )
                    if not will_retry:
                        if availability_failure and health_enabled:
                            health, transition = record_model_failure(
                                selected_model_id, _model_error_category(exc),
                                threshold=settings.model_circuit_failure_threshold,
                                cooldown_seconds=settings.model_circuit_cooldown_seconds,
                            )
                            emit("model_health_failure_recorded", run_id, model_id=selected_model_id, health=health, transition=transition)
                        if failure_decision.fallback_before_first_body:
                            emit("model_local_fallback_activated", run_id, model_id=selected_model_id, reason="upstream_unavailable", health=health)
                            result = _offline_answer(
                                analysis_question, intent_route, playbook_selection, execution_plan, loop_guard,
                                context_resolution, fallback_reason="upstream_unavailable",
                            )
                            result.update({
                                "model": "local-rules", "usage": total_usage,
                                "context_resolution": context_resolution.to_dict(),
                                "model_health": {"requested_model_id": selected_model_id, "fallback_reason": "upstream_unavailable", **health},
                            })
                            for item in result["tool_trace"]:
                                await _notify(progress, {"event": "tool_started", "tool": item["tool"], "arguments": {}})
                                await _notify(progress, {"event": "tool_finished", **item})
                            await _stream_answer(progress, result["answer"])
                            return result
                        raise
                    delay_seconds = _model_retry_delay(settings.model_retry_base_seconds, attempt, exc)
                    emit(
                        "model_call_retry_scheduled",
                        run_id,
                        iteration=iteration + 1,
                        attempt=attempt,
                        next_attempt=attempt + 1,
                        delay_ms=round(delay_seconds * 1000, 1),
                        error_type=type(exc).__name__,
                    )
                    await _notify(progress, {
                        "event": "stage",
                        "stage": "retrying",
                        "iteration": iteration + 1,
                        "attempt": attempt + 1,
                        "message": f"模型服务暂时不可用，正在进行第 {attempt + 1} 次请求",
                    })
                    await asyncio.sleep(delay_seconds)
                    continue
                emit(
                    "model_call_finished",
                    run_id,
                    status="success",
                    phase="agent_loop",
                    iteration=iteration + 1,
                    attempt=attempt,
                    model=connection.model,
                    duration_ms=round((time.perf_counter() - model_started) * 1000, 1),
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    finish_reason=stream_state.get("finish_reason") or (
                        "tool_calls" if assistant.get("tool_calls") else "stop"
                    ),
                    response_id=response_id,
                    first_content_ms=stream_state.get("first_content_ms"),
                    max_content_gap_ms=stream_state.get("max_content_gap_ms", 0),
                    content_delta_count=stream_state.get("content_delta_count", 0),
                    content_chars=stream_state.get("content_chars", 0),
                    stream_duration_ms=stream_state.get("stream_duration_ms"),
                    reasoning_length=int(stream_state.get("reasoning_length", 0)),
                    content_length=len(str(assistant.get("content") or "")),
                    thinking_requested=thinking,
                    thinking_effective=thinking,
                    reasoning_effort=request_payload.get("reasoning_effort"),
                    full_content={"response": _audit_assistant(assistant)},
                )
                thinking_answer_effective = thinking_answer_effective or thinking
                if health_enabled:
                    health, transition = record_model_success(selected_model_id)
                    if transition:
                        emit("model_circuit_recovered", run_id, model_id=selected_model_id, health=health)
                break
            for key in total_usage:
                total_usage[key] += int(usage.get(key, 0) or 0)
            messages.append(assistant)
            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                raw_answer = assistant.get("content") or (
                    loop_guard.termination_answer()
                    if loop_guard.force_synthesis
                    else "分析完成，但模型没有返回文字。"
                )
                if intent_route.intent == "general_knowledge":
                    raw_answer = _normalize_general_knowledge_answer(raw_answer)
                disclosure = knowledge_fallback.get("disclosure")
                if (
                    knowledge_fallback["used"]
                    and disclosure
                    and not _has_knowledge_fallback_disclosure(raw_answer)
                ):
                    raw_answer = f"> {disclosure}\n\n{raw_answer}"
                synthesis = synthesize_legacy_answer(raw_answer, answer_contract, list(sources.values()))
                _emit_answer_synthesis(run_id, synthesis.report)
                if (
                    answer_contract.status == "required"
                    or (
                        intent_route.intent == "general_knowledge"
                        and not stream_state.get("answer_emitted")
                    )
                    or not assistant.get("content")
                ):
                    await _notify(progress, {"event": "stage", "stage": "synthesis", "message": "正在按证据等级整理结构化答案"})
                    await _stream_answer(progress, synthesis.answer)
                return _build_result(synthesis.answer, synthesis.report)

            if len(tool_calls) == 1 and tool_calls[0].get("function", {}).get("name") == "submit_analysis":
                raw_arguments = tool_calls[0].get("function", {}).get("arguments") or "{}"
                submission_error: str | None = None
                try:
                    submission = json.loads(raw_arguments)
                    if not isinstance(submission, dict):
                        raise ValueError("结构化答案必须是 JSON 对象")
                except Exception as exc:
                    submission = {}
                    submission_error = str(exc)
                if submission_error and iteration < loop_guard.max_model_iterations - 1:
                    emit(
                        "answer_submission_rejected",
                        run_id,
                        iteration=iteration + 1,
                        error_type="invalid_json",
                        error_message=submission_error,
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_calls[0].get("id") or "submit-analysis-invalid",
                        "content": json.dumps({
                            "ok": False,
                            "error": "submit_analysis 参数不是完整 JSON，请缩短内容并重新提交。",
                        }, ensure_ascii=False),
                    })
                    await _notify(progress, {
                        "event": "stage",
                        "stage": "synthesis",
                        "message": "结构化答案不完整，正在精简并重新提交",
                    })
                    continue
                synthesis = synthesize_submission(
                    submission,
                    answer_contract,
                    list(sources.values()),
                    status="structured" if submission else "repaired",
                )
                await _notify(progress, {"event": "stage", "stage": "synthesis", "message": "结构化答案已通过证据约束，正在输出"})
                _emit_answer_synthesis(run_id, synthesis.report)
                await _stream_answer(progress, synthesis.answer)
                return _build_result(synthesis.answer, synthesis.report)

            loop_guard.begin_round()
            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                tool_started = time.perf_counter()
                raw_arguments = function.get("arguments") or "{}"
                arguments, parse_error = _parse_tool_arguments(raw_arguments)

                if name == "submit_analysis":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id") or "submit-analysis-rejected",
                        "content": json.dumps({
                            "ok": False,
                            "error": "submit_analysis 必须单独调用，不能与数据工具处于同一轮。",
                        }, ensure_ascii=False),
                    })
                    continue

                await _notify(progress, {"event": "tool_started", "tool": name, "arguments": arguments})
                emit(
                    "tool_call_started",
                    run_id,
                    tool=name or "unknown",
                    tool_call_id=call.get("id"),
                    full_content={"arguments": arguments},
                )
                decision = loop_guard.check_call(name or "unknown", arguments)
                if not decision.allowed:
                    tool_duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                    blocked_item = {
                        "tool": name or "unknown",
                        "arguments": arguments,
                        "status": "blocked",
                        "error_code": decision.reason_code,
                        "error": decision.message,
                        "duration_ms": tool_duration_ms,
                    }
                    trace.append(blocked_item)
                    evidence_observations.append(EvidenceObservation(
                        name or "unknown",
                        arguments,
                        "blocked",
                        error=decision.message,
                    ))
                    await _notify(progress, {"event": "tool_finished", **blocked_item})
                    emit(
                        "tool_call_blocked",
                        run_id,
                        tool=name or "unknown",
                        tool_call_id=call.get("id"),
                        reason_code=decision.reason_code,
                        signature_hash=decision.signature_hash,
                        duration_ms=tool_duration_ms,
                        full_content={"arguments": arguments, "message": decision.message},
                    )
                    emit(
                        "tool_call_finished",
                        run_id,
                        status="blocked",
                        tool=name or "unknown",
                        duration_ms=tool_duration_ms,
                        error_code=decision.reason_code,
                    )
                    content = json.dumps(
                        {"ok": False, "error_code": decision.reason_code, "error": decision.message},
                        ensure_ascii=False,
                    )
                    messages.append({"role": "tool", "tool_call_id": call.get("id") or decision.signature_hash, "content": content})
                    continue

                try:
                    if parse_error is not None:
                        raise ValueError(f"工具参数不是有效 JSON 对象: {parse_error}")
                    result = _execute_registered_tool(name, arguments)
                    if name == "search_knowledge":
                        raw_count = len(result) if isinstance(result, list) else 0
                        result = [
                            item for item in result
                            if isinstance(item, dict)
                            and _usable_knowledge_result(str(arguments.get("query") or ""), item)
                        ] if isinstance(result, list) else []
                        if len(result) != raw_count:
                            emit(
                                "knowledge_results_filtered",
                                run_id,
                                raw_count=raw_count,
                                usable_count=len(result),
                                filtered_count=raw_count - len(result),
                            )
                        for source in result:
                            sources[source["reference_id"]] = source
                    loop_guard.record_result(name, result, True)
                    planned_step = next((
                        step for step in execution_plan.steps
                        if step.tool == name and step.parameters == arguments
                    ), None)
                    evidence_observations.append(EvidenceObservation(
                        name, arguments, "success", result,
                        source_ref=f"TOOL:{planned_step.step_id}" if planned_step else f"TOOL:{call.get('id') or name}",
                    ))
                    row_count = len(result) if isinstance(result, list) else 1
                    tool_duration_ms = round((time.perf_counter() - tool_started) * 1000, 1)
                    trace.append({"tool": name, "arguments": arguments, "status": "ok", "rows": row_count, "duration_ms": tool_duration_ms})
                    await _notify(progress, {
                        "event": "tool_finished",
                        "tool": name,
                        "arguments": arguments,
                        "status": "ok",
                        "rows": row_count,
                        "duration_ms": tool_duration_ms,
                    })
                    emit(
                        "tool_call_finished",
                        run_id,
                        status="success",
                        tool=name,
                        duration_ms=tool_duration_ms,
                        rows=row_count,
                        full_content={"result": result},
                    )
                    content = json.dumps({"ok": True, "data": result}, ensure_ascii=False, default=str)
                except Exception as exc:
                    loop_guard.record_result(name or "unknown", None, False)
                    evidence_observations.append(EvidenceObservation(
                        name or "unknown", arguments, "error", error=str(exc),
                        source_ref=f"TOOL:{call.get('id') or name or 'unknown'}",
                    ))
                    trace.append({"tool": name or "unknown", "arguments": arguments, "status": "error", "error": str(exc)})
                    await _notify(progress, {
                        "event": "tool_finished",
                        "tool": name or "unknown",
                        "arguments": arguments,
                        "status": "error",
                        "error": str(exc),
                    })
                    emit(
                        "tool_call_finished",
                        run_id,
                        status="error",
                        tool=name or "unknown",
                        duration_ms=round((time.perf_counter() - tool_started) * 1000, 1),
                        error_type=type(exc).__name__,
                        full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
                    )
                    content = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": call.get("id") or decision.signature_hash, "content": content})

            loop_guard.finish_round()
            evidence_validation = validate_evidence(execution_plan, selected_playbook, evidence_observations)
            coverage = evidence_validation.coverage
            if (
                execution_plan.status == "ready"
                and coverage["required_total"] > 0
                and coverage["required_covered"] == coverage["required_total"]
            ):
                loop_guard.enter_synthesis(
                    "required_evidence_complete",
                    f"执行计划的 {coverage['required_total']} 组必需证据已全部覆盖。",
                )
            if intent_route.intent != "general_knowledge":
                knowledge_fallback = _knowledge_fallback_state(intent_route, evidence_observations, sources)
            answer_contract = create_answer_contract(
                evidence_validation,
                list(sources.values()),
                allow_model_knowledge_fallback=knowledge_fallback["used"],
                question=question,
                resolved_question=analysis_question,
            )
            messages.append({"role": "system", "content": validator_system_message(evidence_validation)})
            messages.append({"role": "system", "content": synthesizer_system_message(answer_contract)})
            await _notify(progress, {
                "event": "stage",
                "stage": "validation",
                "message": (
                    "证据校验完成 · "
                    f"必需证据 {evidence_validation.coverage['required_covered']}/"
                    f"{evidence_validation.coverage['required_total']} · "
                    f"结论强度 {evidence_validation.allowed_conclusion_strength}"
                ),
                "validation": evidence_validation.to_dict(),
            })
            _emit_evidence_validation(run_id, iteration + 1, evidence_validation.to_dict())
            if knowledge_fallback["used"] and not fallback_announced:
                fallback_announced = True
                emit(
                    "knowledge_fallback_enabled",
                    run_id,
                    reason=knowledge_fallback["reason"],
                    model=connection.model,
                )
                await _notify(progress, {
                    "event": "stage",
                    "stage": "knowledge_fallback",
                    "message": "知识库未检索到相关内容，正在使用模型通用知识补充回答",
                    "knowledge_fallback": knowledge_fallback,
                })
            guard_summary = loop_guard.summary()
            emit(
                "loop_guard_round_finished",
                run_id,
                iteration=iteration + 1,
                total_calls=guard_summary["total_calls"],
                unique_evidence_results=guard_summary["unique_evidence_results"],
                blocked_calls=guard_summary["blocked_calls"],
                consecutive_no_progress_rounds=guard_summary["consecutive_no_progress_rounds"],
                force_synthesis=guard_summary["force_synthesis"],
                stop_reason=guard_summary["stop_reason"],
            )

    loop_guard.enter_synthesis(
        "model_iteration_limit",
        f"模型已达到 {loop_guard.max_model_iterations} 轮执行上限。",
    )
    answer = loop_guard.termination_answer()
    synthesis = synthesize_legacy_answer(answer, answer_contract, list(sources.values()))
    _emit_answer_synthesis(run_id, synthesis.report)
    await _stream_answer(progress, synthesis.answer)
    return _build_result(synthesis.answer, synthesis.report)
