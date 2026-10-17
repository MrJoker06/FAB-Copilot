"""Ready-plan final synthesis, with live legacy dependencies injected per call."""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


READY_SYNTHESIS_MAX_TOKENS = 8192
DEEPSEEK_THINKING_READY_SYNTHESIS_MAX_TOKENS = 32768
SYNTHESIS_REPAIR_MAX_TOKENS = 2048
SYNTHESIS_REPAIR_MAX_SECONDS = 10.0


def ready_synthesis_max_tokens(provider: str, thinking: bool) -> int:
    """Reserve enough completion budget for DeepSeek reasoning before submit_analysis."""
    return DEEPSEEK_THINKING_READY_SYNTHESIS_MAX_TOKENS if provider == "deepseek" and thinking else READY_SYNTHESIS_MAX_TOKENS


def _invalid_submit_arguments(assistant: dict[str, Any]) -> str | None:
    """Return malformed submit_analysis arguments, never interpreting prose."""
    calls = assistant.get("tool_calls") or []
    if len(calls) != 1 or calls[0].get("function", {}).get("name") != "submit_analysis":
        return None
    raw = calls[0].get("function", {}).get("arguments") or "{}"
    try:
        value = json.loads(raw)
        return None if isinstance(value, dict) else str(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(raw)


def valid_submit_analysis(assistant: dict[str, Any]) -> dict[str, Any] | None:
    """Accept only the sole allowed correction output; never coerce prose."""
    calls = assistant.get("tool_calls") or []
    if len(calls) != 1 or calls[0].get("function", {}).get("name") != "submit_analysis":
        return None
    try:
        value = json.loads(calls[0].get("function", {}).get("arguments") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


_SALVAGEABLE_SUBMISSION_FIELDS = {
    "analysis_protocol_version": str, "conclusion": str,
    "conclusion_evidence_refs": list, "conclusion_claim": dict, "facts": list,
    "inferences": list, "hypotheses": list, "recommendations": list,
    "limitations": list, "source_refs": list,
}


def salvage_submit_analysis(raw_arguments: str) -> dict[str, Any] | None:
    """Recover only independently complete top-level JSON values from a cut payload."""
    decoder = json.JSONDecoder()
    recovered: dict[str, Any] = {}
    index = 0
    length = len(raw_arguments)
    def skip_space(position: int) -> int:
        while position < length and raw_arguments[position].isspace():
            position += 1
        return position
    index = skip_space(index)
    if index >= length or raw_arguments[index] != "{":
        return None
    index += 1
    while True:
        index = skip_space(index)
        if index >= length or raw_arguments[index] == "}":
            break
        try:
            field, index = decoder.raw_decode(raw_arguments, index)
        except (TypeError, ValueError, json.JSONDecodeError):
            break
        if not isinstance(field, str):
            break
        index = skip_space(index)
        if index >= length or raw_arguments[index] != ":":
            break
        index = skip_space(index + 1)
        try:
            value, index = decoder.raw_decode(raw_arguments, index)
        except (TypeError, ValueError, json.JSONDecodeError):
            break
        expected = _SALVAGEABLE_SUBMISSION_FIELDS.get(field)
        if expected is not None and isinstance(value, expected):
            recovered[field] = value
        index = skip_space(index)
        if index >= length:
            break
        if raw_arguments[index] == "}":
            break
        if raw_arguments[index] != ",":
            break
        index += 1
    substantive = any(recovered.get(field) for field in (
        "conclusion", "facts", "inferences", "hypotheses", "recommendations",
    ))
    if not substantive:
        return None
    limitations = recovered.get("limitations")
    if not isinstance(limitations, list):
        limitations = []
        recovered["limitations"] = limitations
    limitations.append(
        "submit_analysis 参数被截断；服务端仅保留了可独立解析的字段，未推断缺失内容。"
    )
    recovered["_repair_events"] = [{
        "reason": "truncated_submit_analysis",
        "affected_field": "parseable_top_level_fields",
        "outcome": "deterministic_partial_salvage",
    }]
    return recovered


async def request_synthesis_correction(
    client: Any,
    endpoint: str,
    headers: dict[str, str],
    connection: Any,
    messages: list[dict[str, str]],
    invalid_arguments: str,
    completion_token_budget: int,
    wall_time_seconds: float,
    run_id: str,
    iteration: int,
    *,
    deps: "ReadySynthesisDependencies",
) -> tuple[dict[str, Any] | None, dict[str, Any], str | None, str]:
    """Make the single allowed synthesis-only correction request.

    The caller owns the combined original+repair budget.  A correction never
    receives business tools, and callers must locally synthesize on any error.
    """
    max_tokens = min(SYNTHESIS_REPAIR_MAX_TOKENS, max(0, completion_token_budget))
    if max_tokens <= 0 or wall_time_seconds <= 0:
        return None, {}, None, "budget_exhausted"
    payload = {
        "model": connection.model,
        "messages": [
            *messages,
            {"role": "system", "content": "上一条 submit_analysis 参数不完整。仅修复为一个完整 JSON 对象并再次调用 submit_analysis；不得输出正文、不得调用任何业务工具、不得补造证据。"},
            {"role": "user", "content": json.dumps({"invalid_submit_analysis": invalid_arguments[:6000]}, ensure_ascii=False)},
        ],
        "temperature": 0,
        "tools": [deps.submit_analysis_tool],
        "max_tokens": max_tokens,
        **deps.provider_request_options(connection.provider, False),
    }
    if connection.provider != "deepseek":
        payload["tool_choice"] = "auto"
    state: dict[str, Any] = {"answer_emitted": False, "suppress_embedded_tool_json": True}
    started = deps.perf_counter()
    deps.emit("model_call_started", run_id, phase="synthesis_repair", iteration=iteration,
              attempt=1, model=connection.model, message_count=len(payload["messages"]),
              business_tool_selection_enabled=False, completion_token_budget=max_tokens,
              wall_time_budget_ms=round(wall_time_seconds * 1000, 1))
    try:
        assistant, usage, response_id = await asyncio.wait_for(
            deps.stream_completion(client, endpoint, headers, payload, None, state),
            timeout=wall_time_seconds,
        )
    except Exception as exc:
        deps.emit("model_call_finished", run_id, status="error", phase="synthesis_repair",
                  iteration=iteration, attempt=1, model=connection.model,
                  duration_ms=round((deps.perf_counter() - started) * 1000, 1),
                  error_type=type(exc).__name__, answer_emitted=False,
                  business_tool_selection_enabled=False, repair_outcome="local_fallback")
        return None, {}, None, "unavailable_or_timeout"
    deps.emit("model_call_finished", run_id, status="success", phase="synthesis_repair",
              iteration=iteration, attempt=1, model=connection.model,
              duration_ms=round((deps.perf_counter() - started) * 1000, 1),
              input_tokens=usage.get("prompt_tokens", 0), output_tokens=usage.get("completion_tokens", 0),
              total_tokens=usage.get("total_tokens", 0), answer_emitted=False,
              business_tool_selection_enabled=False, repair_outcome="submitted")
    return assistant, usage, response_id, "submitted"


@dataclass(slots=True)
class ReadySynthesisDependencies:
    submit_analysis_tool: dict[str, Any]
    synthesizer_system_message: Callable[[Any], str]
    synthesize_legacy_answer: Callable[..., Any]
    synthesize_submission: Callable[..., Any]
    ready_synthesis_fallback: Callable[[Any, Any, list[Any], str], Any]
    provider_request_options: Callable[[str, bool], dict[str, Any]]
    stream_completion: Callable[..., Awaitable[tuple[dict, dict, str | None]]]
    retryable_model_error: Callable[[Exception], bool]
    model_failure_reason: Callable[[Exception], str]
    model_retry_delay: Callable[[float, int, Exception], float]
    audit_assistant: Callable[[dict | None], dict]
    emit: Callable[..., None]
    stage_memory_messages: Callable[[str, list[dict] | None], list[dict[str, str]]]
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep
    perf_counter: Callable[[], float] = time.perf_counter


def ready_synthesis_messages(
    question: str,
    plan: Any,
    validation: Any,
    contract: Any,
    observations: list[Any],
    *,
    deps: ReadySynthesisDependencies,
) -> list[dict[str, str]]:
    evidence = [
        {
            "source_ref": item.source_ref,
            "tool": item.tool,
            "status": item.status,
            "result": item.result if item.status == "success" else None,
            "error": item.error,
        }
        for item in observations
    ]
    task = {
        "question": question,
        "plan_id": plan.plan_id,
        "intent": plan.route_intent,
        "playbook_id": plan.playbook_id,
        "playbook_version": plan.playbook_version,
        "scope": {
            "type": plan.scope_contract.primary_scope_type,
            "ids": plan.scope_contract.primary_scope_ids,
        },
        "validation": {
            "coverage": validation.coverage,
            "risks": [item.message for item in validation.risks],
            "conflicts": [item.message for item in validation.conflicts],
            "allowed_conclusion_strength": validation.allowed_conclusion_strength,
        },
        "analysis_protocol": {
            "version": "2.0",
            "direct_facts": "声明语义、范围、时间和角色；调用级来源的 kind/grain 由服务端补全。",
            "composite_inferences": "关联至少两个已验证事实索引，并给出面向用户的依据和不确定性。",
        },
        "evidence": evidence,
    }
    return deps.stage_memory_messages("ready_synthesis", None) + [
        {
            "role": "system",
            "content": "你是 Fab Copilot 的最终综合器。业务工具已由服务端确定性执行；你只能依据下面的已验证证据调用 submit_analysis 一次，不能选择、请求或虚构业务工具。",
        },
        {"role": "system", "content": deps.synthesizer_system_message(contract)},
        {
            "role": "user",
            "content": json.dumps(
                task, ensure_ascii=False, separators=(",", ":"), default=str
            ),
        },
    ]


def ready_synthesis_fallback(
    validation: Any,
    contract: Any,
    observations: list[Any],
    reason: str,
    *,
    deps: ReadySynthesisDependencies,
) -> Any:
    succeeded = [item.source_ref for item in observations if item.status == "success"]
    failed = [item.source_ref for item in observations if item.status != "success"]
    coverage = validation.coverage
    lines = [
        "确定性取证已经完成，但模型综合阶段未能生成可验证的结构化结论。",
        f"必需证据覆盖 {coverage['required_covered']}/{coverage['required_total']}；允许的结论强度为 {validation.allowed_conclusion_strength}。",
        f"已完成来源：{', '.join(item for item in succeeded if item) or '无'}。",
    ]
    if failed:
        lines.append(f"未完成来源：{', '.join(item for item in failed if item)}。")
    lines.append(
        f"综合降级原因：{reason}。请稍后重试模型综合；本次不会重复执行制造数据工具。"
    )
    return deps.synthesize_legacy_answer(
        "\n\n".join(lines), contract,
        repair_events=({
            "reason": reason,
            "affected_field": "submit_analysis",
            "outcome": "local_evidence_safe_fallback",
        },),
    )


def synthesize_ready_assistant(
    assistant: dict[str, Any],
    contract: Any,
    sources: list[dict],
    validation: Any,
    observations: list[Any],
    run_id: str,
    *,
    deps: ReadySynthesisDependencies,
) -> Any:
    """Accept exactly one structured submit_analysis call, with legacy fallback behavior."""
    tool_calls = assistant.get("tool_calls") or []
    if (
        len(tool_calls) == 1
        and tool_calls[0].get("function", {}).get("name") == "submit_analysis"
    ):
        try:
            raw_arguments = tool_calls[0].get("function", {}).get("arguments") or "{}"
            submission = json.loads(raw_arguments)
            if not isinstance(submission, dict):
                raise ValueError("submit_analysis 参数必须是 JSON 对象")
            return deps.synthesize_submission(
                submission, contract, sources, status="structured",
                repair_events=tuple(assistant.get("_server_repair_events", ())),
            )
        except Exception as exc:
            deps.emit(
                "answer_submission_rejected",
                run_id,
                iteration=1,
                error_type="invalid_json",
                error_message=str(exc),
                execution_mode="synthesis_only",
                repair_reason="truncated_or_invalid_submit_analysis",
                repair_outcome="local_evidence_safe_fallback",
            )
            salvaged = salvage_submit_analysis(raw_arguments)
            if salvaged is not None:
                repair_events = tuple(salvaged.pop("_repair_events", ()))
                return deps.synthesize_submission(
                    salvaged, contract, sources, status="repaired", repair_events=repair_events,
                )
            return deps.ready_synthesis_fallback(
                validation,
                contract,
                observations,
                "模型提交的结构化结果无效",
            )
    raw_content = str(assistant.get("content") or "")
    if not tool_calls and raw_content.strip():
        return deps.synthesize_legacy_answer(raw_content, contract, sources)
    return deps.ready_synthesis_fallback(
        validation,
        contract,
        observations,
        "模型没有提交允许的 submit_analysis 结果",
    )


async def request_ready_synthesis(
    client: Any,
    endpoint: str,
    headers: dict[str, str],
    connection: Any,
    settings: Any,
    messages: list[dict[str, str]],
    run_id: str,
    thinking: bool,
    retry_budget: int,
    *,
    deps: ReadySynthesisDependencies,
) -> tuple[dict[str, Any], dict[str, Any], str | None, dict[str, Any]]:
    payload: dict[str, Any] = {
        "model": connection.model,
        "messages": messages,
        "temperature": 0.15,
        "tools": [deps.submit_analysis_tool],
        "max_tokens": ready_synthesis_max_tokens(connection.provider, thinking),
        **deps.provider_request_options(connection.provider, thinking),
    }
    if not (connection.provider == "deepseek" and thinking):
        payload["tool_choice"] = "auto"
    for attempt in range(1, retry_budget + 2):
        started = deps.perf_counter()
        deps.emit(
            "model_call_started",
            run_id,
            phase="ready_plan_synthesis",
            iteration=1,
            attempt=attempt,
            model=connection.model,
            message_count=len(messages),
            thinking_requested=thinking,
            thinking_effective=thinking,
            reasoning_effort=payload.get("reasoning_effort"),
            business_tool_selection_enabled=False,
            full_content={"request": payload},
        )
        state: dict[str, Any] = {
            "answer_emitted": False,
            "suppress_embedded_tool_json": True,
        }
        try:
            assistant, usage, response_id = await deps.stream_completion(
                client, endpoint, headers, payload, None, state
            )
        except Exception as exc:
            retryable = deps.retryable_model_error(exc)
            will_retry = retryable and attempt <= retry_budget
            deps.emit(
                "model_call_finished",
                run_id,
                status="error",
                phase="ready_plan_synthesis",
                iteration=1,
                attempt=attempt,
                model=connection.model,
                duration_ms=round((deps.perf_counter() - started) * 1000, 1),
                error_type=type(exc).__name__,
                retryable=retryable,
                will_retry=will_retry,
                answer_emitted=False,
                business_tool_selection_enabled=False,
                failure_reason=deps.model_failure_reason(exc),
                full_content={
                    "error_message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            if not will_retry:
                raise
            delay = deps.model_retry_delay(
                settings.model_retry_base_seconds, attempt, exc
            )
            deps.emit(
                "model_call_retry_scheduled",
                run_id,
                phase="ready_plan_synthesis",
                attempt=attempt,
                next_attempt=attempt + 1,
                delay_ms=round(delay * 1000, 1),
                error_type=type(exc).__name__,
            )
            await deps.sleep(delay)
            continue
        deps.emit(
            "model_call_finished",
            run_id,
            status="success",
            phase="ready_plan_synthesis",
            iteration=1,
            attempt=attempt,
            model=connection.model,
            duration_ms=round((deps.perf_counter() - started) * 1000, 1),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            finish_reason=state.get("finish_reason")
            or ("tool_calls" if assistant.get("tool_calls") else "stop"),
            response_id=response_id,
            first_content_ms=state.get("first_content_ms"),
            max_content_gap_ms=state.get("max_content_gap_ms", 0),
            content_delta_count=state.get("content_delta_count", 0),
            content_chars=state.get("content_chars", 0),
            stream_duration_ms=state.get("stream_duration_ms"),
            reasoning_length=int(state.get("reasoning_length", 0)),
            content_length=len(str(assistant.get("content") or "")),
            thinking_requested=thinking,
            thinking_effective=thinking,
            reasoning_effort=payload.get("reasoning_effort"),
            business_tool_selection_enabled=False,
            full_content={"response": deps.audit_assistant(assistant)},
        )
        invalid_arguments = _invalid_submit_arguments(assistant)
        if invalid_arguments is not None:
            token_cap = ready_synthesis_max_tokens(connection.provider, thinking)
            used = int(usage.get("completion_tokens", 0) or 0)
            repaired, repair_usage, repair_response_id, repair_outcome = await request_synthesis_correction(
                client, endpoint, headers, connection, messages, invalid_arguments,
                token_cap - used, SYNTHESIS_REPAIR_MAX_SECONDS - (deps.perf_counter() - started),
                run_id, 1, deps=deps,
            )
            if repaired is not None:
                repaired_submission = valid_submit_analysis(repaired)
                if repaired_submission is not None:
                    repaired["_server_repair_events"] = ({
                        "reason": "truncated_or_invalid_submit_analysis",
                        "affected_field": "submit_analysis",
                        "outcome": "model_correction_accepted",
                    },)
                    repaired["tool_calls"][0]["function"]["arguments"] = json.dumps(repaired_submission, ensure_ascii=False)
                    assistant = repaired
                    response_id = repair_response_id or response_id
                    usage = {
                        key: int(usage.get(key, 0) or 0) + int(repair_usage.get(key, 0) or 0)
                        for key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                    }
                    deps.emit("answer_submission_repair", run_id, iteration=1,
                              repair_reason="truncated_or_invalid_submit_analysis",
                              repair_outcome=repair_outcome)
                else:
                    deps.emit("answer_submission_repair", run_id, iteration=1,
                              repair_reason="truncated_or_invalid_submit_analysis",
                              repair_outcome="invalid_correction_response")
            else:
                deps.emit("answer_submission_repair", run_id, iteration=1,
                          repair_reason="truncated_or_invalid_submit_analysis",
                          repair_outcome=repair_outcome)
        return assistant, usage, response_id, state
    raise RuntimeError("模型综合请求未返回结果")
