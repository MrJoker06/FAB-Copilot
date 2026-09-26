"""Conversation-context preparation with dependencies injected by ``app.agent_runtime.service``."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from ..contracts import ContextStageResult
from ...memory_system.context.protocol import (
    ContextPayloadValidationError,
    ContextProtocolError,
    context_json_arguments,
    context_protocol_correction,
    normalized_context_protocol_error,
    strip_json_fence,
    validate_contextualizer_payload,
)
from ...memory_system.ports import ContextModelResult, ContextResolveRequest
from ...memory_system.service import ContextService


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


async def _resolve_with_memory_service(
    question: str,
    history: list[dict] | None,
    settings: Any,
    run_id: str,
    progress: Any,
    direct_route: Any,
    thinking: bool,
    health_model_id: str | None,
    health_recovery_trial: bool,
    deps: ResolverDependencies,
) -> tuple[Any, dict]:
    deterministic = deps.resolve_question_context(question, history)
    connection = settings.model_connection
    eligible = not (
        deterministic.applied
        or not connection.api_key
        or (direct_route is not None and direct_route.intent == "conversation")
        or (
            not history
            and (direct_route is None or direct_route.intent != "unknown")
        )
    )
    if not eligible:
        return deterministic, {}

    class Events:
        def emit(self, event_type: str, event_run_id: str, **fields: Any) -> None:
            deps.emit(event_type, event_run_id, **fields)

        async def notify(self, event_progress: Any, event: dict) -> None:
            await deps.notify(event_progress, event)

    class Clock:
        def perf_counter(self) -> float:
            return deps.perf_counter()

        async def sleep(self, seconds: float) -> None:
            await deps.sleep(seconds)

    class Policy:
        def failure_reason(self, error: Exception) -> str:
            return deps.failure_reason(error)

        def retryable(self, error: Exception) -> bool:
            return deps.retryable_error(error)

        def retry_delay(self, base_seconds: float, retry_number: int, error: Exception) -> float:
            return deps.retry_delay(base_seconds, retry_number, error)

        def audit_assistant(self, assistant: dict | None) -> dict:
            return deps.audit_assistant(assistant)

        def fingerprint(self, content: str) -> str:
            return deps.content_fingerprint(content)

    class Health:
        def failure(self, error: Exception, protocol_error: Exception | None) -> None:
            if health_model_id and deps.retryable_error(error):
                health, transition = deps.record_failure(
                    health_model_id,
                    deps.error_category(error),
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

        def success(self) -> None:
            if health_model_id:
                health, transition = deps.record_success(health_model_id)
                if transition:
                    deps.emit(
                        "model_circuit_recovered",
                        run_id,
                        model_id=health_model_id,
                        health=health,
                    )

    class Rules:
        response_format = deps.response_format

        def build_messages(
            self, rules_question: str, rules_history: list[dict] | None
        ) -> list[dict]:
            return deps.build_messages(rules_question, rules_history)

        def semantic_resolution(
            self,
            rules_question: str,
            arguments: dict,
            rules_history: list[dict] | None,
        ) -> Any:
            return deps.semantic_resolution(
                rules_question,
                arguments,
                rules_history,
            )

        def unresolved(
            self,
            rules_question: str,
            source: str,
            *,
            failure_reason: str = "",
        ) -> Any:
            return deps.unresolved_context(
                rules_question,
                source,
                failure_reason=failure_reason,
            )

    endpoint = f"{connection.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {connection.api_key}",
        "Content-Type": "application/json",
    }

    class Model:
        @asynccontextmanager
        async def open(self):
            async with deps.async_client(timeout=settings.api_timeout_seconds) as client:
                yield Session(client)

        def timeout_error(self) -> Exception:
            return httpx.ReadTimeout("contextualization deadline exceeded")

    class Session:
        def __init__(self, client: Any):
            self._client = client

        async def complete(
            self,
            payload: dict,
            timeout_seconds: float,
        ) -> ContextModelResult:
            stream_state: dict[str, Any] = {}
            try:
                async with deps.timeout(timeout_seconds):
                    assistant, usage, response_id = await deps.stream_completion(
                        self._client,
                        endpoint,
                        headers,
                        payload,
                        None,
                        stream_state,
                    )
                return ContextModelResult(assistant, usage, response_id, stream_state)
            except TimeoutError as exc:
                mapped = httpx.ReadTimeout("contextualization deadline exceeded")
                mapped.stream_state = stream_state
                raise mapped from exc
            except Exception as exc:
                exc.stream_state = stream_state
                raise

    request = ContextResolveRequest(
        question=question,
        history=history,
        model=connection.model,
        provider_options=lambda: deps.provider_options(connection.provider, False),
        timeout_seconds=float(getattr(settings, "model_context_timeout_seconds", 15.0)),
        retry_base_seconds=settings.model_retry_base_seconds,
        max_retries=settings.model_max_retries,
        run_id=run_id,
        thinking=thinking,
        eligible_for_model=True,
        health_recovery_trial=health_recovery_trial,
    )
    return await ContextService(
        model=Model(),
        events=Events(),
        policy=Policy(),
        clock=Clock(),
        rules=Rules(),
        health=Health(),
    ).resolve_turn(request, deterministic, progress)


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
    return await _resolve_with_memory_service(
        question, history, settings, run_id, progress, direct_route, thinking,
        health_model_id, health_recovery_trial, deps,
    )


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
