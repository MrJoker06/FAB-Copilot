from __future__ import annotations

from typing import Annotated, Any

import uvicorn
from fab_agent import FabAnalysisAgent, ModelConfig
from fab_contracts import AdHocQueryRequest, ApiEnvelope, IdentityContext, ProblemDetail, ReportRequest
from fab_core import DataGateway, DomainError, ReportService
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .application_routes import build_application_router
from .identity import DevelopmentIdentityProvider
from .mcp_gateway import MCPDataGateway
from .middleware import RequestIDMiddleware, current_request_id
from .monitoring import AuditReader
from .repositories import KnowledgeRepository, SessionRepository
from .settings import APISettings


def create_app(settings: APISettings | None = None, gateway: DataGateway | None = None) -> FastAPI:
    resolved = settings or APISettings()
    data_gateway = gateway or MCPDataGateway(resolved)
    reports = ReportService(data_gateway)
    database_dir = resolved.resolved_application_database_dir()
    knowledge = KnowledgeRepository(database_dir / "process_knowledge.db")
    agent = FabAnalysisAgent(
        data_gateway,
        ModelConfig(
            api_key=resolved.model_api_key,
            base_url=resolved.model_base_url,
            model=resolved.model_name,
            timeout_seconds=resolved.model_timeout_seconds,
            max_tool_rounds=resolved.model_max_tool_rounds,
            api_key_source="environment" if resolved.model_api_key else "none",
        ),
        knowledge=knowledge,
    )
    identities = DevelopmentIdentityProvider(resolved)
    app = FastAPI(
        title="Fab Insight API",
        version="2.0.0",
        description="Versioned API, Agent and knowledge service for Fab Insight V2",
    )
    app.add_middleware(RequestIDMiddleware)

    def identity(authorization: Annotated[str | None, Header()] = None) -> IdentityContext:
        return identities.resolve(authorization, current_request_id())

    app.include_router(
        build_application_router(
            knowledge,
            SessionRepository(database_dir / "ai_operations.db"),
            AuditReader(resolved.resolved_audit_log_dir()),
            agent,
            identity,
        )
    )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        problem = ProblemDetail(
            title="Request failed",
            status=exc.status_code,
            detail=exc.detail,
            instance=str(request.url.path),
            error_code=exc.error_code,
            request_id=current_request_id(),
            retryable=exc.retryable,
            category="dependency" if exc.status_code in {502, 503, 504} else "client",
        )
        return JSONResponse(
            problem.model_dump(mode="json"),
            status_code=exc.status_code,
            media_type="application/problem+json",
        )

    @app.get("/api/v1/health/live")
    async def live() -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(
            data={"status": "ok", "service": "fab-api", "version": "2.0.0"}, request_id=current_request_id()
        )

    @app.get("/api/v1/health/ready")
    async def ready() -> JSONResponse:
        mcp_health = await data_gateway.health()
        status = 200 if mcp_health.get("ok") else 503
        payload = ApiEnvelope(
            data={
                "status": "ready" if status == 200 else "degraded",
                "dependencies": {"data_mcp": mcp_health},
            },
            request_id=current_request_id(),
        )
        return JSONResponse(payload.model_dump(mode="json"), status_code=status)

    @app.get("/api/v1/reports/dashboard")
    async def dashboard(
        start: str | None = None,
        end: str | None = None,
        current: IdentityContext = Depends(identity),
    ) -> ApiEnvelope[dict[str, Any]]:
        request = ReportRequest.model_validate({"start": start, "end": end})
        result = await reports.run("get_dashboard", request, current)
        return ApiEnvelope(data=result.data, request_id=current_request_id())

    @app.get("/api/v1/reports/capability")
    async def capability(
        process_step: str = Query("CVD", min_length=2, max_length=32),
        start: str | None = None,
        end: str | None = None,
        current: IdentityContext = Depends(identity),
    ) -> ApiEnvelope[Any]:
        result = await reports.run(
            "get_process_capability",
            ReportRequest.model_validate({"start": start, "end": end, "process_step": process_step}),
            current,
        )
        return ApiEnvelope(data=result.data, request_id=current_request_id())

    @app.post("/api/v1/tools/query")
    async def ad_hoc_query(
        payload: AdHocQueryRequest,
        current: IdentityContext = Depends(identity),
    ) -> ApiEnvelope[Any]:
        result = await data_gateway.call_tool(
            "query_manufacturing_data", payload.model_dump(mode="json"), current
        )
        return ApiEnvelope(data=result.data, request_id=current_request_id())

    web_dist = resolved.resolved_web_dist()
    if web_dist.exists():
        assets = web_dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            requested = web_dist / path
            return FileResponse(requested if requested.is_file() else web_dist / "index.html")

    return app


def main() -> None:
    settings = APISettings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


app = create_app()
