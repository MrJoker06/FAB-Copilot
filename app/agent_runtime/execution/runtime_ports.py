"""Consumer-owned asynchronous ports for the runtime pilot."""

from __future__ import annotations

from typing import Protocol

from ..tools.contracts import ToolExecutionContext, ToolResult
from .runtime_contracts import (
    ModelRequest,
    ModelResponse,
    RuntimeContext,
    RuntimeEvent,
)


class ModelResponsePort(Protocol):
    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse: ...


class ToolDispatcherPort(Protocol):
    async def dispatch(
        self,
        name: str,
        raw_arguments: object,
        context: ToolExecutionContext[None],
    ) -> ToolResult[object]: ...


class EventSink(Protocol):
    async def emit(self, event: RuntimeEvent) -> None: ...
