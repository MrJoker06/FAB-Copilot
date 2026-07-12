from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import run_agent
from .audit import monitoring_summary, read_events
from .config import PROJECT_DIR, get_settings
from .database import db_session
from .reports import process_capability, report_bundle
from .seed import generate_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if not settings.database_path.exists():
        generate_database(settings.database_path)
    yield


app = FastAPI(
    title="Fab Insight Agent",
    version="1.0.0",
    description="虚拟半导体制造报表、RAG 与数据分析 Agent",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=PROJECT_DIR / "app" / "static"), name="static")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(PROJECT_DIR / "app" / "static" / "index.html")


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    with db_session() as connection:
        lots = connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
        date_range = connection.execute("SELECT MIN(date(start_time)), MAX(date(COALESCE(complete_time, start_time))) FROM lots").fetchone()
    return {
        "status": "ok",
        "database": {"lots": lots, "start": date_range[0], "end": date_range[1]},
        "model": settings.deepseek_model,
        "agent_configured": bool(settings.deepseek_api_key),
    }


@app.get("/api/reports/dashboard")
def dashboard(start: str | None = None, end: str | None = None) -> dict:
    try:
        return report_bundle(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/reports/capability")
def capability(
    process_step: str = Query("CVD", pattern="^(LITHO|ETCH|CVD|CMP)$"),
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    try:
        return process_capability(start, end, process_step)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    try:
        return await run_agent(request.message, [item.model_dump() for item in request.history])
    except httpx.HTTPStatusError as exc:
        detail = f"DeepSeek API 返回 {exc.response.status_code}"
        try:
            api_error = exc.response.json().get("error", {}).get("message")
            if api_error:
                detail += f": {api_error}"
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"无法连接 DeepSeek API: {exc}") from exc


@app.get("/api/monitor/summary")
def monitor_summary(
    hours: int = Query(24, ge=1, le=720),
    recent_limit: int = Query(20, ge=1, le=100),
) -> dict:
    return monitoring_summary(hours, recent_limit)


@app.get("/api/monitor/events")
def monitor_events(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return list(reversed(read_events(limit)))
