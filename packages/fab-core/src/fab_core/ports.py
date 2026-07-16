from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from fab_contracts import IdentityContext, ReportRequest, ToolResult


class DataGateway(Protocol):
    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        identity: IdentityContext,
    ) -> ToolResult: ...

    async def health(self) -> dict[str, Any]: ...


class IdentityProvider(Protocol):
    def resolve(self, authorization: str | None, request_id: str) -> IdentityContext: ...


JobCallable = Callable[..., Awaitable[None] | None]


class JobDispatcher(Protocol):
    def submit(self, job: JobCallable, *args: Any) -> None: ...


class ReportService:
    def __init__(self, gateway: DataGateway) -> None:
        self._gateway = gateway

    async def run(self, tool_name: str, request: ReportRequest, identity: IdentityContext) -> ToolResult:
        return await self._gateway.call_tool(
            tool_name,
            request.model_dump(mode="json", exclude_none=True),
            identity,
        )
