from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from .agent import run_agent
from .audit import emit, monitoring_summary, read_events
from .config import PROJECT_DIR, get_settings, public_model_config, update_model_config
from .database import db_session
from .processes import MANUFACTURING_STEPS, PROCESS_STEP_PATTERN
from .rag import (
    get_historical_case,
    get_knowledge_document,
    list_historical_cases,
    list_knowledge_documents,
    search_knowledge,
)
from .reports import process_capability, report_bundle
from .seed import generate_database, seed_reference_data


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if not settings.database_path.exists():
        generate_database(settings.database_path)
    else:
        seed_reference_data(settings.database_path)
        with db_session(settings.database_path) as connection:
            populated_steps = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT process_step FROM process_runs WHERE measurement_value IS NOT NULL"
                )
            }
        if not set(MANUFACTURING_STEPS).issubset(populated_steps):
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


class ModelConfigRequest(BaseModel):
    model: str
    api_key: SecretStr | None = None


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(PROJECT_DIR / "app" / "static" / "index.html")


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    with db_session() as connection:
        lots = connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
        date_range = connection.execute("SELECT MIN(date(start_time)), MAX(date(COALESCE(complete_time, start_time))) FROM lots").fetchone()
        knowledge_chunks = connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        historical_cases = connection.execute("SELECT COUNT(*) FROM historical_cases").fetchone()[0]
    return {
        "status": "ok",
        "database": {"lots": lots, "start": date_range[0], "end": date_range[1]},
        "model": settings.deepseek_model,
        "agent_configured": bool(settings.deepseek_api_key),
        "reference_data": {"knowledge_chunks": knowledge_chunks, "historical_cases": historical_cases},
    }


@app.get("/api/settings/model")
def get_model_config() -> dict:
    return public_model_config()


@app.post("/api/settings/model")
def set_model_config(request: ModelConfigRequest) -> dict:
    api_key = request.api_key.get_secret_value() if request.api_key is not None else None
    try:
        result = update_model_config(request.model, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    emit(
        "model_config_changed",
        f"config-{uuid.uuid4()}",
        status="success",
        model=result["model"],
        api_key_updated=bool(api_key),
        api_key_source=result["api_key_source"],
    )
    return result


@app.get("/api/reports/dashboard")
def dashboard(start: str | None = None, end: str | None = None) -> dict:
    try:
        return report_bundle(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/reports/capability")
def capability(
    process_step: str = Query("CVD", pattern=PROCESS_STEP_PATTERN),
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    try:
        return process_capability(start, end, process_step)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/knowledge/documents")
def knowledge_documents() -> list[dict]:
    return list_knowledge_documents()


@app.get("/api/knowledge/chunks/{chunk_id}")
def knowledge_document(chunk_id: int) -> dict:
    try:
        return get_knowledge_document(chunk_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases")
def historical_cases() -> list[dict]:
    return list_historical_cases()


@app.get("/api/cases/{case_id}")
def historical_case(case_id: str) -> dict:
    try:
        return get_historical_case(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/rag/search")
def rag_search(
    q: str = Query(min_length=2, max_length=500),
    limit: int = Query(6, ge=1, le=10),
    process_step: str | None = None,
    equipment_id: str | None = None,
    defect_type: str | None = None,
    source_type: list[str] | None = Query(None),
) -> dict:
    results = search_knowledge(q, limit, process_step, equipment_id, defect_type, source_type)
    return {"query": q, "count": len(results), "results": results}


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
