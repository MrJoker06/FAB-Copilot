"""Contextual-memory resolution use case, independent of HTTP and Agent state."""
from __future__ import annotations

import traceback
from typing import Any

from .context.history import build_contextualizer_messages
from .context.protocol import (
    CONTEXTUALIZER_RESPONSE_FORMAT,
    ContextProtocolError,
    context_json_arguments,
    context_protocol_correction,
    normalized_context_protocol_error,
)
from .context.resolver import semantic_context_resolution, unresolved_context
from .contracts import ContextResolution
from .ports import (
    ContextClock,
    ContextEvents,
    ContextHealthObserver,
    ContextModel,
    ContextResolveRequest,
    ContextRetryPolicy,
    ContextRules,
)


class DefaultContextRules:
    """The canonical Memory implementation of contextualization rules."""

    response_format = CONTEXTUALIZER_RESPONSE_FORMAT

    def build_messages(self, question: str, history: list[dict] | None) -> list[dict]:
        return build_contextualizer_messages(question, history)

    def semantic_resolution(
        self, question: str, arguments: dict, history: list[dict] | None
    ) -> ContextResolution:
        return semantic_context_resolution(question, arguments, history)

    def unresolved(
        self, question: str, source: str, *, failure_reason: str = ""
    ) -> ContextResolution:
        return unresolved_context(question, source, failure_reason=failure_reason)


class ContextService:
    def __init__(
        self,
        *,
        model: ContextModel,
        events: ContextEvents,
        policy: ContextRetryPolicy,
        clock: ContextClock,
        rules: ContextRules | None = None,
        health: ContextHealthObserver | None = None,
    ):
        self._model = model
        self._events = events
        self._policy = policy
        self._clock = clock
        self._rules = rules or DefaultContextRules()
        self._health = health

    async def resolve_turn(
        self,
        request: ContextResolveRequest,
        deterministic: ContextResolution,
        progress: Any = None,
    ) -> tuple[ContextResolution, dict]:
        if deterministic.applied or not request.eligible_for_model:
            return deterministic, {}

        await self._events.notify(
            progress,
            {
                "event": "stage",
                "stage": "context",
                "message": "正在结合当前会话理解这条消息",
            },
        )
        request_payload = {
            "model": request.model,
            "messages": self._rules.build_messages(request.question, request.history),
            "temperature": 0,
            "response_format": self._rules.response_format,
            "max_tokens": 1200,
            **request.provider_options(),
        }
        deadline = self._clock.perf_counter() + request.timeout_seconds

        async def fallback(
            exc: Exception,
            protocol_error: ContextProtocolError | None = None,
        ) -> tuple[ContextResolution, dict]:
            failure_reason = self._policy.failure_reason(exc)
            if self._health:
                self._health.failure(exc, protocol_error)
            self._events.emit(
                "question_context_resolution_failed",
                request.run_id,
                error_type=type(exc).__name__,
                failure_reason=failure_reason,
                resolution_state="unavailable",
                relation="standalone",
                applied=False,
                fallback_action="continue_with_original_question",
            )
            await self._events.notify(
                progress,
                {
                    "event": "stage",
                    "stage": "context",
                    "message": "未能可靠恢复上文指代",
                },
            )
            return self._rules.unresolved(
                request.question,
                "fallback",
                failure_reason=failure_reason,
            ), {}

        # Opening is outside retry/fallback by design: client creation errors
        # historically escaped unchanged and do not create an attempt audit.
        async with self._model.open() as model:
            attempt = protocol_failures = transport_failures = 0
            while True:
                if deadline <= self._clock.perf_counter():
                    return await fallback(self._model.timeout_error())
                attempt += 1
                started = self._clock.perf_counter()
                assistant: dict | None = None
                stream_state: dict[str, Any] = {}
                self._events.emit(
                    "model_call_started",
                    request.run_id,
                    phase="contextualization",
                    attempt=attempt,
                    model=request.model,
                    message_count=len(request_payload["messages"]),
                    thinking_requested=request.thinking,
                    thinking_effective=False,
                    reasoning_effort=request_payload.get("reasoning_effort"),
                    full_content={"request": request_payload},
                )
                try:
                    remaining = deadline - self._clock.perf_counter()
                    if remaining <= 0:
                        raise self._model.timeout_error()
                    result = await model.complete(request_payload, remaining)
                    assistant = result.assistant
                    usage = result.usage
                    response_id = result.response_id
                    stream_state = result.stream_state
                    resolution = self._rules.semantic_resolution(
                        request.question,
                        context_json_arguments(
                            assistant,
                            protocol_error=self._protocol_error,
                        ),
                        request.history,
                    )
                    if resolution.source == "fallback":
                        raise self._protocol_error(
                            "invalid_message_id",
                            "上下文解析器引用了当前历史窗口之外的消息",
                            str(assistant.get("content") or ""),
                        )
                except Exception as exc:
                    stream_state = getattr(exc, "stream_state", stream_state)
                    protocol_error = (
                        exc if isinstance(exc, ContextProtocolError) else None
                    )
                    if protocol_error:
                        protocol_error = normalized_context_protocol_error(
                            protocol_error,
                            stream_state.get("finish_reason"),
                        )
                        exc = protocol_error
                        protocol_failures += 1
                        retryable = True
                        will_retry = (
                            protocol_failures < 2
                            and not request.health_recovery_trial
                            and deadline > self._clock.perf_counter()
                        )
                        retry_delay = 0.0
                    else:
                        retryable = self._policy.retryable(exc)
                        if retryable:
                            transport_failures += 1
                        retry_delay = (
                            self._policy.retry_delay(
                                request.retry_base_seconds,
                                transport_failures,
                                exc,
                            )
                            if retryable
                            else 0.0
                        )
                        remaining = deadline - self._clock.perf_counter()
                        will_retry = (
                            retryable
                            and transport_failures <= request.max_retries
                            and not request.health_recovery_trial
                            and retry_delay < remaining
                        )
                    self._events.emit(
                        "model_call_finished",
                        request.run_id,
                        status="error",
                        phase="contextualization",
                        attempt=attempt,
                        model=request.model,
                        duration_ms=round(
                            (self._clock.perf_counter() - started) * 1000,
                            1,
                        ),
                        error_type=type(exc).__name__,
                        retryable=retryable,
                        will_retry=will_retry,
                        protocol_error_code=(
                            protocol_error.code if protocol_error else None
                        ),
                        response_length=(
                            protocol_error.response_length if protocol_error else None
                        ),
                        response_fingerprint=(
                            protocol_error.response_fingerprint
                            if protocol_error
                            else None
                        ),
                        finish_reason=stream_state.get("finish_reason"),
                        reasoning_length=int(stream_state.get("reasoning_length", 0)),
                        content_length=len(
                            str((assistant or {}).get("content") or "")
                        ),
                        thinking_requested=request.thinking,
                        thinking_effective=False,
                        reasoning_effort=request_payload.get("reasoning_effort"),
                        failure_reason=self._policy.failure_reason(exc),
                        full_content={
                            "error_message": str(exc),
                            "traceback": traceback.format_exc(),
                            "response": self._policy.audit_assistant(assistant),
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
                                        int(request_payload.get("max_tokens", 1200))
                                        * 2,
                                        2400,
                                    ),
                                    2400,
                                )
                            request_payload["messages"] = [
                                *request_payload["messages"],
                                context_protocol_correction(protocol_error),
                            ]
                        else:
                            await self._clock.sleep(retry_delay)
                        continue
                    return await fallback(exc, protocol_error)

                self._events.emit(
                    "model_call_finished",
                    request.run_id,
                    status="success",
                    phase="contextualization",
                    attempt=attempt,
                    model=request.model,
                    duration_ms=round(
                        (self._clock.perf_counter() - started) * 1000,
                        1,
                    ),
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    finish_reason=stream_state.get("finish_reason") or "stop",
                    reasoning_length=int(stream_state.get("reasoning_length", 0)),
                    content_length=len(str(assistant.get("content") or "")),
                    thinking_requested=request.thinking,
                    thinking_effective=False,
                    reasoning_effort=request_payload.get("reasoning_effort"),
                    response_id=response_id,
                    full_content={
                        "response": self._policy.audit_assistant(assistant),
                        "context_resolution": resolution.to_dict(),
                    },
                )
                if self._health:
                    self._health.success()
                self._events.emit(
                    "question_context_classified",
                    request.run_id,
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
                    original_length=len(request.question),
                    resolved_length=len(resolution.resolved_question),
                )
                await self._events.notify(
                    progress,
                    {
                        "event": "stage",
                        "stage": "context",
                        "message": (
                            "已结合上文恢复当前消息的完整目标"
                            if resolution.applied
                            else "未可靠关联到上文，将按当前消息独立判断"
                            if resolution.relation != "standalone"
                            else "已确认当前消息是独立问题"
                        ),
                        "context_resolution": resolution.to_dict(),
                    },
                )
                return resolution, usage

    def _protocol_error(
        self,
        code: str,
        message: str,
        content: str,
    ) -> ContextProtocolError:
        error = ContextProtocolError(code, message, content)
        error.response_fingerprint = (
            self._policy.fingerprint(content) if content else None
        )
        return error
