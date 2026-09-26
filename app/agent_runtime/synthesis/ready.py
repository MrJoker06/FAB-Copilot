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


def ready_synthesis_max_tokens(provider: str, thinking: bool) -> int:
    """Reserve enough completion budget for DeepSeek reasoning before submit_analysis."""
    return DEEPSEEK_THINKING_READY_SYNTHESIS_MAX_TOKENS if provider == "deepseek" and thinking else READY_SYNTHESIS_MAX_TOKENS


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
    return deps.synthesize_legacy_answer("\n\n".join(lines), contract)


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
                submission, contract, sources, status="structured"
            )
        except Exception as exc:
            deps.emit(
                "answer_submission_rejected",
                run_id,
                iteration=1,
                error_type="invalid_json",
                error_message=str(exc),
                execution_mode="synthesis_only",
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
        return assistant, usage, response_id, state
    raise RuntimeError("模型综合请求未返回结果")
