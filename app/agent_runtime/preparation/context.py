"""Conversation-context preparation with dependencies injected by ``app.agent``."""

from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from ..contracts import ContextStageResult
from ...context_resolver import (
    ContextPayloadValidationError,
    validate_contextualizer_payload,
)
from ...audit import content_fingerprint


class ContextProtocolError(ValueError):
    def __init__(self, code: str, message: str, content: str = ""):
        super().__init__(message)
        self.code = code
        self.response_length = len(content)
        self.response_fingerprint = content_fingerprint(content) if content else None


def strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if not lines or not re.fullmatch(r"```(?:json)?\s*", lines[0], re.IGNORECASE):
        return stripped
    if len(lines) < 3 or lines[-1].strip() != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip()


def context_json_arguments(
    assistant: dict, *, protocol_error: Callable[[str, str, str], Exception]
) -> dict:
    content = assistant.get("content")
    if not isinstance(content, str) or not content.strip():
        raise protocol_error("empty_response", "上下文解析器必须返回一个 JSON 对象", "")
    cleaned = strip_json_fence(content)
    try:
        arguments = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise protocol_error(
            "invalid_json", "上下文解析结果不是合法 JSON", content
        ) from exc
    try:
        return validate_contextualizer_payload(arguments)
    except ContextPayloadValidationError as exc:
        raise protocol_error(exc.code, str(exc), content) from exc


def context_protocol_correction(error: ContextProtocolError) -> dict:
    return {
        "role": "user",
        "content": (
            "上一次上下文分类响应未通过协议校验"
            f"（{error.code}）。请重新返回一个符合最初契约的 JSON 对象；"
            "不要回答用户问题，不要省略必需字段。"
        ),
    }


def normalized_context_protocol_error(
    error: ContextProtocolError, finish_reason: str | None
) -> ContextProtocolError:
    if error.code == "empty_response" and finish_reason == "length":
        normalized = ContextProtocolError("context_budget_exhausted", str(error))
        normalized.response_length = error.response_length
        normalized.response_fingerprint = error.response_fingerprint
        return normalized
    return error


@dataclass(slots=True)
class ResolverDependencies:
    resolve_question_context: Callable[..., Any]
    unresolved_context: Callable[..., Any]
    build_messages: Callable[..., list[dict]]
    response_format: dict
    provider_options: Callable[..., dict]
    stream_completion: Callable[..., Awaitable[tuple[dict, dict, str | None]]]
    semantic_resolution: Callable[..., Any]
    notify: Callable[..., Awaitable[None]]
    emit: Callable[..., None]
    perf_counter: Callable[[], float]
    async_client: Any
    timeout: Callable[..., Any]
    sleep: Callable[[float], Awaitable[None]]
    failure_reason: Callable[[Exception], str]
    retryable_error: Callable[[Exception], bool]
    error_category: Callable[[Exception], str]
    retry_delay: Callable[[float, int, Exception], float]
    audit_assistant: Callable[[dict | None], dict]
    record_failure: Callable[..., tuple[dict, str | None]]
    record_success: Callable[..., tuple[dict, str | None]]
    content_fingerprint: Callable[[str], str]


@dataclass(slots=True)
class ContextStageDependencies:
    resolver: ResolverDependencies
    notify: Callable[..., Awaitable[None]]
    emit: Callable[..., None]
    perf_counter: Callable[[], float]
    isinstance_settings: Callable[[Any], bool]
    public_model_config: Callable[[], dict]
    route_question: Callable[[str], Any]
    get_model_health: Callable[[str], dict]
    claim_model_call: Callable[..., tuple[bool, dict, str | None]]
    resolve_turn: Callable[..., Awaitable[tuple[Any, dict]]]


async def resolve_conversation_turn(
    question: str,
    history: list[dict] | None,
    settings: Any,
    run_id: str,
    progress: Any,
    direct_route: Any = None,
    thinking: bool = False,
    health_model_id: str | None = None,
    health_recovery_trial: bool = False,
    *,
    deps: ResolverDependencies,
) -> tuple[Any, dict]:
    deterministic = deps.resolve_question_context(question, history)
    connection = settings.model_connection
    if deterministic.applied or not connection.api_key:
        return deterministic, {}
    if direct_route is not None and direct_route.intent == "conversation":
        return deterministic, {}
    if not history and (direct_route is None or direct_route.intent != "unknown"):
        return deterministic, {}
    await deps.notify(
        progress,
        {
            "event": "stage",
            "stage": "context",
            "message": "正在结合当前会话理解这条消息",
        },
    )
    request_payload = {
        "model": connection.model,
        "messages": deps.build_messages(question, history),
        "temperature": 0,
        "response_format": deps.response_format,
        "max_tokens": 1200,
        **deps.provider_options(connection.provider, False),
    }
    endpoint = f"{connection.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {connection.api_key}",
        "Content-Type": "application/json",
    }
    deadline = deps.perf_counter() + float(
        getattr(settings, "model_context_timeout_seconds", 15.0)
    )

    async def fallback(
        exc: Exception, protocol_error: ContextProtocolError | None = None
    ) -> tuple[Any, dict]:
        failure_reason = deps.failure_reason(exc)
        if health_model_id and deps.retryable_error(exc):
            health, transition = deps.record_failure(
                health_model_id,
                deps.error_category(exc),
                threshold=settings.model_circuit_failure_threshold,
                cooldown_seconds=settings.model_circuit_cooldown_seconds,
            )
            deps.emit(
                "model_health_failure_recorded",
                run_id,
                model_id=health_model_id,
                health=health,
                transition=transition,
            )
        elif health_model_id and protocol_error is not None:
            health, transition = deps.record_success(health_model_id)
            if transition:
                deps.emit(
                    "model_circuit_recovered",
                    run_id,
                    model_id=health_model_id,
                    health=health,
                )
        deps.emit(
            "question_context_resolution_failed",
            run_id,
            error_type=type(exc).__name__,
            failure_reason=failure_reason,
            resolution_state="unavailable",
            relation="standalone",
            applied=False,
            fallback_action="continue_with_original_question",
        )
        await deps.notify(
            progress,
            {"event": "stage", "stage": "context", "message": "未能可靠恢复上文指代"},
        )
        return deps.unresolved_context(
            question, "fallback", failure_reason=failure_reason
        ), {}

    async with deps.async_client(timeout=settings.api_timeout_seconds) as client:
        attempt = protocol_failures = transport_failures = 0
        while True:
            if deadline <= deps.perf_counter():
                return await fallback(
                    httpx.ReadTimeout("contextualization deadline exceeded")
                )
            attempt += 1
            started = deps.perf_counter()
            assistant: dict | None = None
            stream_state: dict[str, Any] = {}
            deps.emit(
                "model_call_started",
                run_id,
                phase="contextualization",
                attempt=attempt,
                model=connection.model,
                message_count=len(request_payload["messages"]),
                thinking_requested=thinking,
                thinking_effective=False,
                reasoning_effort=request_payload.get("reasoning_effort"),
                full_content={"request": request_payload},
            )
            try:
                remaining = deadline - deps.perf_counter()
                if remaining <= 0:
                    raise httpx.ReadTimeout("contextualization deadline exceeded")
                async with deps.timeout(remaining):
                    assistant, usage, response_id = await deps.stream_completion(
                        client, endpoint, headers, request_payload, None, stream_state
                    )
                resolution = deps.semantic_resolution(
                    question,
                    context_json_arguments(
                        assistant,
                        protocol_error=lambda code, message, content: (
                            _new_protocol_error(code, message, content, deps)
                        ),
                    ),
                    history,
                )
                if resolution.source == "fallback":
                    raise _new_protocol_error(
                        "invalid_message_id",
                        "上下文解析器引用了当前历史窗口之外的消息",
                        str(assistant.get("content") or ""),
                        deps,
                    )
            except Exception as exc:
                if isinstance(exc, TimeoutError):
                    exc = httpx.ReadTimeout("contextualization deadline exceeded")
                protocol_error = exc if isinstance(exc, ContextProtocolError) else None
                if protocol_error:
                    protocol_error = normalized_context_protocol_error(
                        protocol_error, stream_state.get("finish_reason")
                    )
                    exc = protocol_error
                    protocol_failures += 1
                    retryable = True
                    will_retry = (
                        protocol_failures < 2
                        and not health_recovery_trial
                        and deadline > deps.perf_counter()
                    )
                else:
                    retryable = deps.retryable_error(exc)
                    if retryable:
                        transport_failures += 1
                    retry_delay = (
                        deps.retry_delay(
                            settings.model_retry_base_seconds, transport_failures, exc
                        )
                        if retryable
                        else 0.0
                    )
                    remaining = deadline - deps.perf_counter()
                    will_retry = (
                        retryable
                        and transport_failures <= settings.model_max_retries
                        and not health_recovery_trial
                        and retry_delay < remaining
                    )
                deps.emit(
                    "model_call_finished",
                    run_id,
                    status="error",
                    phase="contextualization",
                    attempt=attempt,
                    model=connection.model,
                    duration_ms=round((deps.perf_counter() - started) * 1000, 1),
                    error_type=type(exc).__name__,
                    retryable=retryable,
                    will_retry=will_retry,
                    protocol_error_code=protocol_error.code if protocol_error else None,
                    response_length=protocol_error.response_length
                    if protocol_error
                    else None,
                    response_fingerprint=protocol_error.response_fingerprint
                    if protocol_error
                    else None,
                    finish_reason=stream_state.get("finish_reason"),
                    reasoning_length=int(stream_state.get("reasoning_length", 0)),
                    content_length=len(str((assistant or {}).get("content") or "")),
                    thinking_requested=thinking,
                    thinking_effective=False,
                    reasoning_effort=request_payload.get("reasoning_effort"),
                    failure_reason=deps.failure_reason(exc),
                    full_content={
                        "error_message": str(exc),
                        "traceback": traceback.format_exc(),
                        "response": deps.audit_assistant(assistant),
                    },
                )
                if will_retry:
                    if protocol_error:
                        if protocol_error.code in {
                            "empty_response",
                            "context_budget_exhausted",
                        }:
                            request_payload["max_tokens"] = min(
                                max(
                                    int(request_payload.get("max_tokens", 1200)) * 2,
                                    2400,
                                ),
                                2400,
                            )
                        request_payload["messages"] = [
                            *request_payload["messages"],
                            context_protocol_correction(protocol_error),
                        ]
                    else:
                        await deps.sleep(retry_delay)
                    continue
                return await fallback(exc, protocol_error)
            deps.emit(
                "model_call_finished",
                run_id,
                status="success",
                phase="contextualization",
                attempt=attempt,
                model=connection.model,
                duration_ms=round((deps.perf_counter() - started) * 1000, 1),
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                finish_reason=stream_state.get("finish_reason") or "stop",
                reasoning_length=int(stream_state.get("reasoning_length", 0)),
                content_length=len(str(assistant.get("content") or "")),
                thinking_requested=thinking,
                thinking_effective=False,
                reasoning_effort=request_payload.get("reasoning_effort"),
                response_id=response_id,
                full_content={
                    "response": deps.audit_assistant(assistant),
                    "context_resolution": resolution.to_dict(),
                },
            )
            if health_model_id:
                health, transition = deps.record_success(health_model_id)
                if transition:
                    deps.emit(
                        "model_circuit_recovered",
                        run_id,
                        model_id=health_model_id,
                        health=health,
                    )
            deps.emit(
                "question_context_classified",
                run_id,
                relation=resolution.relation,
                strategy=resolution.strategy,
                applied=resolution.applied,
                confidence=resolution.confidence,
                resolution_state=resolution.resolution_state,
                failure_reason=resolution.failure_reason or None,
                fallback_action=(
                    "request_history_selection"
                    if resolution.resolution_state == "ambiguous"
                    else None
                ),
                original_length=len(question),
                resolved_length=len(resolution.resolved_question),
            )
            await deps.notify(
                progress,
                {
                    "event": "stage",
                    "stage": "context",
                    "message": "已结合上文恢复当前消息的完整目标"
                    if resolution.applied
                    else "未可靠关联到上文，将按当前消息独立判断"
                    if resolution.relation != "standalone"
                    else "已确认当前消息是独立问题",
                    "context_resolution": resolution.to_dict(),
                },
            )
            return resolution, usage
    return deps.unresolved_context(question, "fallback"), {}


def _new_protocol_error(
    code: str, message: str, content: str, deps: ResolverDependencies
) -> ContextProtocolError:
    error = ContextProtocolError(code, message, content)
    error.response_fingerprint = deps.content_fingerprint(content) if content else None
    return error


async def prepare_context_stage(
    question: str,
    history: list[dict] | None,
    settings: Any,
    run_id: str,
    progress: Any,
    thinking: bool,
    context_started: float,
    *,
    deps: ContextStageDependencies,
) -> ContextStageResult:
    health_enabled = deps.isinstance_settings(settings)
    selected_model_id = (
        deps.public_model_config()["model"]
        if health_enabled
        else settings.model_connection.model
    )
    direct_route = deps.route_question(question)
    needs_upstream = (
        bool(settings.model_connection.api_key)
        and bool(history or direct_route.intent == "unknown")
        and not deps.resolver.resolve_question_context(question, history).applied
    )
    allowed, health = True, {"status": "unknown"}
    recovery_trial = False
    if health_enabled:
        health = deps.get_model_health(selected_model_id)
    if needs_upstream and health_enabled:
        allowed, health, transition = deps.claim_model_call(
            selected_model_id,
            cooldown_seconds=settings.model_circuit_cooldown_seconds,
            lease_seconds=settings.model_circuit_recovery_lease_seconds,
        )
        if transition:
            recovery_trial = transition in {"recovery_started", "recovery_reclaimed"}
            deps.emit(
                "model_circuit_recovery_started",
                run_id,
                model_id=selected_model_id,
                health=health,
            )
    if needs_upstream and not allowed:
        resolution, usage = (
            deps.resolver.unresolved_context(
                question, "circuit_open", failure_reason="circuit_open"
            ),
            {},
        )
        deps.emit(
            "model_local_fallback_context_bypassed",
            run_id,
            model_id=selected_model_id,
            health=health,
        )
    else:
        resolution, usage = await deps.resolve_turn(
            question,
            history,
            settings,
            run_id,
            progress,
            direct_route,
            thinking,
            selected_model_id if needs_upstream and health_enabled else None,
            recovery_trial,
        )
    if resolution.applied:
        deps.emit(
            "question_context_resolved",
            run_id,
            strategy=resolution.strategy,
            original_length=len(question),
            resolved_length=len(resolution.resolved_question),
        )
        if resolution.source == "deterministic":
            await deps.notify(
                progress,
                {
                    "event": "stage",
                    "stage": "context",
                    "message": "已根据上条回答中的选项恢复分析目标",
                    "context_resolution": resolution.to_dict(),
                },
            )
    elif resolution.resolution_state == "unavailable":
        deps.emit(
            "question_context_degraded",
            run_id,
            resolution_state=resolution.resolution_state,
            relation=resolution.relation,
            applied=False,
            failure_reason=resolution.failure_reason or None,
            fallback_action="continue_with_original_question",
        )
    deps.emit(
        "context_stage_completed",
        run_id,
        status="degraded"
        if resolution.resolution_state == "unavailable"
        else "success",
        resolution_state=resolution.resolution_state,
        strategy=resolution.strategy,
        applied=resolution.applied,
        duration_ms=round((deps.perf_counter() - context_started) * 1000, 1),
    )
    return ContextStageResult(resolution, usage, direct_route, selected_model_id)
