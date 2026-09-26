"""Small side-effect ports for the contextual-memory use case."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncContextManager, Awaitable, Callable, Protocol


class HistoryReader(Protocol):
    """Read the authenticated session transcript for one turn."""

    def read(self, session_id: str, limit: int = 20) -> list[dict]: ...


@dataclass(frozen=True)
class ContextModelResult:
    assistant: dict | None
    usage: dict
    response_id: str | None
    stream_state: dict[str, Any]


class ContextModelSession(Protocol):
    def complete(self, payload: dict, timeout_seconds: float) -> Awaitable[ContextModelResult]: ...


class ContextModel(Protocol):
    def open(self) -> AsyncContextManager[ContextModelSession]: ...
    def timeout_error(self) -> Exception: ...


class ContextRules(Protocol):
    response_format: dict

    def build_messages(self, question: str, history: list[dict] | None) -> list[dict]: ...
    def semantic_resolution(
        self, question: str, arguments: dict, history: list[dict] | None
    ) -> Any: ...
    def unresolved(
        self, question: str, source: str, *, failure_reason: str = ""
    ) -> Any: ...


class ContextEvents(Protocol):
    def emit(self, event_type: str, run_id: str, **fields: Any) -> None: ...
    def notify(self, progress: Any, event: dict) -> Awaitable[None]: ...


class ContextRetryPolicy(Protocol):
    def failure_reason(self, error: Exception) -> str: ...
    def retryable(self, error: Exception) -> bool: ...
    def retry_delay(self, base_seconds: float, retry_number: int, error: Exception) -> float: ...
    def audit_assistant(self, assistant: dict | None) -> dict: ...
    def fingerprint(self, content: str) -> str: ...


class ContextHealthObserver(Protocol):
    def failure(self, error: Exception, protocol_error: Exception | None) -> None: ...
    def success(self) -> None: ...


class ContextClock(Protocol):
    def perf_counter(self) -> float: ...
    def sleep(self, seconds: float) -> Awaitable[None]: ...


@dataclass(frozen=True)
class ContextResolveRequest:
    question: str
    history: list[dict] | None
    model: str
    provider_options: Callable[[], dict]
    timeout_seconds: float
    retry_base_seconds: float
    max_retries: int
    run_id: str
    thinking: bool
    eligible_for_model: bool
    health_recovery_trial: bool = False
