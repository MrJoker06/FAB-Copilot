from __future__ import annotations

import contextlib
import contextvars
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from fab_contracts import IdentityContext
from mcp.server.fastmcp import Context, FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .service import DataToolService
from .settings import DataMCPSettings

CURRENT_IDENTITY: contextvars.ContextVar[IdentityContext | None] = contextvars.ContextVar(
    "fab_mcp_identity",
    default=None,
)


def _headers(scope: Scope) -> dict[str, str]:
    return {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}


class ServiceIdentityMiddleware:
    def __init__(self, app: ASGIApp, service_token: str) -> None:
        self.app = app
        self.service_token = service_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        authorization = headers.get("authorization", "")
        if authorization != f"Bearer {self.service_token}":
            payload = json.dumps(
                {"error_code": "MCP_AUTHENTICATION_REQUIRED", "detail": "invalid service credential"}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(payload)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": payload})
            return
        request_id = headers.get("x-request-id") or f"mcp-{uuid.uuid4()}"
        user_id = headers.get("x-fab-user-id") or "local-user"
        roles = tuple(filter(None, headers.get("x-fab-roles", "analyst").split(",")))
        scopes = tuple(filter(None, headers.get("x-fab-scopes", "analytics:adhoc").split(",")))
        sites = tuple(filter(None, headers.get("x-fab-site-ids", "DEMO-FAB").split(",")))
        token = CURRENT_IDENTITY.set(
            IdentityContext(
                user_id=user_id,
                roles=roles,
                scopes=scopes,
                site_ids=sites,
                request_id=request_id,
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT_IDENTITY.reset(token)


def _identity(ctx: Context[Any, Any]) -> IdentityContext:
    identity = CURRENT_IDENTITY.get()
    if identity is not None:
        return identity
    return IdentityContext(
        user_id="local-user",
        roles=("analyst",),
        scopes=("analytics:adhoc",),
        site_ids=("DEMO-FAB",),
        request_id=str(ctx.request_id or f"mcp-{uuid.uuid4()}"),
    )


def create_mcp(service: DataToolService) -> FastMCP:
    mcp = FastMCP(
        "Fab Data MCP",
        instructions="Read-only governed manufacturing analytics tools.",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
    )

    def invoke(name: str, arguments: dict[str, Any], ctx: Context[Any, Any]) -> dict[str, Any]:
        return service.call(name, arguments, _identity(ctx)).model_dump(mode="json")

    @mcp.tool()
    def get_fab_overview(
        ctx: Context[Any, Any], start: str | None = None, end: str | None = None
    ) -> dict[str, Any]:
        """Query fab lot, wafer, yield, cycle-time and excursion overview."""
        return invoke("get_fab_overview", {"start": start, "end": end}, ctx)

    @mcp.tool()
    def get_yield_trend(
        ctx: Context[Any, Any],
        start: str | None = None,
        end: str | None = None,
        product: str | None = None,
    ) -> dict[str, Any]:
        """Query weekly yield and cycle-time trend."""
        return invoke("get_yield_trend", {"start": start, "end": end, "product": product}, ctx)

    @mcp.tool()
    def get_equipment_health(
        ctx: Context[Any, Any], start: str | None = None, end: str | None = None
    ) -> dict[str, Any]:
        """Query equipment runs, excursions and downtime health."""
        return invoke("get_equipment_health", {"start": start, "end": end}, ctx)

    @mcp.tool()
    def get_equipment_productivity(
        ctx: Context[Any, Any], start: str | None = None, end: str | None = None
    ) -> dict[str, Any]:
        """Query SEMI E10 equipment productivity states."""
        return invoke("get_equipment_productivity", {"start": start, "end": end}, ctx)

    @mcp.tool()
    def get_process_capability(
        process_step: str,
        ctx: Context[Any, Any],
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """Query equipment process capability for one process step."""
        return invoke(
            "get_process_capability",
            {"start": start, "end": end, "process_step": process_step},
            ctx,
        )

    @mcp.tool()
    def get_defect_pareto(
        ctx: Context[Any, Any],
        start: str | None = None,
        end: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Query defect Pareto distribution."""
        return invoke("get_defect_pareto", {"start": start, "end": end, "limit": limit}, ctx)

    @mcp.tool()
    def get_recent_excursions(
        ctx: Context[Any, Any],
        start: str | None = None,
        end: str | None = None,
        process_step: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Query recent process excursions."""
        return invoke(
            "get_recent_excursions",
            {"start": start, "end": end, "process_step": process_step, "limit": limit},
            ctx,
        )

    @mcp.tool()
    def get_sensor_summary(
        ctx: Context[Any, Any],
        start: str | None = None,
        end: str | None = None,
        process_step: str | None = None,
        equipment_id: str | None = None,
        signal_name: str | None = None,
    ) -> dict[str, Any]:
        """Query governed sensor aggregates."""
        return invoke(
            "get_sensor_summary",
            {
                "start": start,
                "end": end,
                "process_step": process_step,
                "equipment_id": equipment_id,
                "signal_name": signal_name,
            },
            ctx,
        )

    @mcp.tool()
    def query_manufacturing_data(sql: str, ctx: Context[Any, Any]) -> dict[str, Any]:
        """Execute one AST-validated read-only query against allowlisted manufacturing tables."""
        return invoke("query_manufacturing_data", {"sql": sql}, ctx)

    return mcp


def create_app(settings: DataMCPSettings | None = None) -> ASGIApp:
    resolved = settings or DataMCPSettings()
    service = DataToolService(resolved)
    mcp = create_mcp(service)

    async def live(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "fab-data-mcp", "version": "2.0.0"})

    async def ready(_: Request) -> JSONResponse:
        missing = [str(path) for path in resolved.resolved_database_paths().values() if not path.exists()]
        status = 503 if missing else 200
        return JSONResponse(
            {"status": "not_ready" if missing else "ready", "missing": missing}, status_code=status
        )

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    starlette = Starlette(
        routes=[
            Route("/health/live", live),
            Route("/health/ready", ready),
            Mount("/", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )
    return ServiceIdentityMiddleware(starlette, resolved.service_token)


def main() -> None:
    settings = DataMCPSettings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


app = create_app()
