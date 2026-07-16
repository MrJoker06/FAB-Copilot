from __future__ import annotations

import json
from typing import Any

import httpx
from fab_contracts import IdentityContext, ToolResult
from fab_core import DomainError
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .settings import APISettings


class MCPDataGateway:
    def __init__(self, settings: APISettings) -> None:
        self.settings = settings

    def _headers(self, identity: IdentityContext) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.mcp_service_token}",
            "X-Request-ID": identity.request_id,
            "X-Fab-User-ID": identity.user_id,
            "X-Fab-Roles": ",".join(identity.roles),
            "X-Fab-Scopes": ",".join(identity.scopes),
            "X-Fab-Site-IDs": ",".join(identity.site_ids),
        }

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        identity: IdentityContext,
    ) -> ToolResult:
        try:
            async with (
                httpx.AsyncClient(
                    headers=self._headers(identity),
                    timeout=self.settings.mcp_timeout_seconds,
                ) as client,
                streamable_http_client(self.settings.mcp_url, http_client=client) as (
                    read_stream,
                    write_stream,
                    _,
                ),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=arguments)
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            raise DomainError(
                "MCP_UNAVAILABLE",
                "manufacturing data service is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        if result.isError:
            detail = "manufacturing data tool rejected the request"
            if result.content:
                detail = str(getattr(result.content[0], "text", detail))[:500]
            raise DomainError("MCP_TOOL_ERROR", detail, status_code=422)
        payload: Any = result.structuredContent
        if payload is None and result.content:
            text = str(getattr(result.content[0], "text", "{}"))
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise DomainError(
                    "MCP_INVALID_RESPONSE", "data service returned invalid JSON", status_code=502
                ) from exc
        return ToolResult.model_validate(payload)

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(self.settings.mcp_health_url)
                payload = response.json()
                return {"ok": response.status_code == 200, **payload}
        except (httpx.HTTPError, ValueError):
            return {"ok": False, "status": "unavailable"}
