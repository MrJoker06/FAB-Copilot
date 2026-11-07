"""Model gateway Port and its OpenAI-compatible HTTP transport adapter.

Runtime paths describe the target with :class:`ModelEndpoint` and obtain one
per-request :class:`ModelSessionPort` from a :class:`ModelGatewayPort`.  Client
construction and shutdown, the Chat Completions URL, credential headers and
chat-template message shaping are owned here, so the Loop, Ready and Context
paths keep only their own retry, health and fallback policies.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

from .message_compat import chat_template_compat_enabled, flatten_system_messages

StreamResult = tuple[dict, dict, str | None]
# ``(client, url, headers, payload, progress, stream_state)``; positional on
# purpose, because legacy patch points replace this callable with test fakes
# that accept exactly these six positional arguments.
StreamCompletion = Callable[..., Awaitable[StreamResult]]
ClientFactory = Callable[..., AbstractAsyncContextManager[Any]]


@dataclass(frozen=True)
class ModelEndpoint:
    """Immutable description of one OpenAI-compatible provider endpoint."""

    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    chat_template: str | None = None

    @classmethod
    def from_connection(
        cls, connection: Any, *, chat_template: str | None = None
    ) -> ModelEndpoint:
        return cls(
            provider=str(getattr(connection, "provider", "") or ""),
            model=str(getattr(connection, "model", "") or ""),
            base_url=str(connection.base_url).rstrip("/"),
            api_key=str(getattr(connection, "api_key", "") or ""),
            chat_template=chat_template,
        )

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @property
    def merges_system_messages(self) -> bool:
        return chat_template_compat_enabled(self.chat_template)

    def prepare_payload(self, payload: dict) -> dict:
        """Return the provider payload; callers' request dicts are never mutated."""
        if not self.merges_system_messages:
            return payload
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return payload
        return {**payload, "messages": flatten_system_messages(messages)}


@runtime_checkable
class ModelSessionPort(Protocol):
    """One open model session; streams a request and returns assistant, usage, id."""

    @property
    def endpoint(self) -> ModelEndpoint | None: ...

    async def stream(
        self,
        payload: dict,
        progress: Any,
        stream_state: dict[str, Any] | None = None,
    ) -> StreamResult: ...


@runtime_checkable
class ModelGatewayPort(Protocol):
    """Model access used by Runtime paths without constructing provider clients."""

    def endpoint_for(
        self, connection: Any, *, chat_template: str | None = None
    ) -> ModelEndpoint: ...

    def open(
        self, endpoint: ModelEndpoint, *, timeout_seconds: float
    ) -> AbstractAsyncContextManager[ModelSessionPort]: ...


class HttpModelSession:
    """Session bound to one owned HTTP client and one endpoint."""

    __slots__ = ("_client", "_endpoint", "_stream_completion")

    def __init__(
        self, client: Any, endpoint: ModelEndpoint, stream_completion: StreamCompletion
    ) -> None:
        self._client = client
        self._endpoint = endpoint
        self._stream_completion = stream_completion

    @property
    def endpoint(self) -> ModelEndpoint:
        return self._endpoint

    async def stream(
        self,
        payload: dict,
        progress: Any,
        stream_state: dict[str, Any] | None = None,
    ) -> StreamResult:
        return await self._stream_completion(
            self._client,
            self._endpoint.chat_completions_url,
            self._endpoint.headers(),
            self._endpoint.prepare_payload(payload),
            progress,
            stream_state,
        )


class HttpModelGateway:
    """ModelGatewayPort over an injected async HTTP client factory and SSE parser."""

    def __init__(
        self,
        *,
        stream_completion: StreamCompletion,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.stream_completion = stream_completion
        self.client_factory = (
            client_factory if client_factory is not None else httpx.AsyncClient
        )

    def endpoint_for(
        self, connection: Any, *, chat_template: str | None = None
    ) -> ModelEndpoint:
        return ModelEndpoint.from_connection(connection, chat_template=chat_template)

    @asynccontextmanager
    async def open(
        self, endpoint: ModelEndpoint, *, timeout_seconds: float
    ) -> AsyncIterator[HttpModelSession]:
        # The client is closed on success, error and cancellation alike.
        async with self.client_factory(timeout=timeout_seconds) as client:
            yield HttpModelSession(client, endpoint, self.stream_completion)


__all__ = [
    "HttpModelGateway",
    "HttpModelSession",
    "ModelEndpoint",
    "ModelGatewayPort",
    "ModelSessionPort",
    "StreamCompletion",
    "StreamResult",
]
