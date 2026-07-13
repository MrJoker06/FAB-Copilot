from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from .agent import run_agent
from .audit import emit, monitoring_summary, read_events
from .config import PROJECT_DIR, get_settings, public_model_config, update_model_config
from .database import db_session, initialize
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
from .sessions import (
    append_message,
    archive_session,
    create_session,
    get_session,
    list_sessions,
    record_agent_result,
    rename_session,
    session_history,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if not settings.database_path.exists():
        generate_database(settings.database_path)
    else:
        with db_session(settings.database_path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
            session_columns = {row[1] for row in connection.execute("PRAGMA table_info(chat_sessions)")}
            run_columns = {row[1] for row in connection.execute("PRAGMA table_info(process_runs)")}
        required_tables = {
            "sensor_readings", "equipment_state_intervals", "wafer_maps",
            "agent_runs", "agent_tool_events", "message_sources",
        }
        needs_migration = (
            not required_tables.issubset(tables)
            or not {"model", "archived_at", "last_message_preview"}.issubset(session_columns)
            or not {"operation_seq", "layer_name", "scenario_id"}.issubset(run_columns)
            or "idx_runs_step_time" not in indexes
        )
        if needs_migration:
            initialize(settings.database_path)
        with db_session(settings.database_path) as connection:
            populated_steps = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT process_step FROM process_runs WHERE measurement_value IS NOT NULL"
                )
            }
            has_sensor_data = bool(connection.execute("SELECT EXISTS(SELECT 1 FROM sensor_readings LIMIT 1)").fetchone()[0])
            max_operation = connection.execute("SELECT MAX(operation_seq) FROM process_runs").fetchone()[0] or 0
            knowledge_count = connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        if not set(MANUFACTURING_STEPS).issubset(populated_steps) or not has_sensor_data or max_operation < 18:
            generate_database(settings.database_path)
        elif knowledge_count == 0:
            seed_reference_data(settings.database_path)
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
    session_id: str | None = None


class ModelConfigRequest(BaseModel):
    model: str
    api_key: SecretStr | None = None


class SessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(
        PROJECT_DIR / "app" / "static" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    with db_session() as connection:
        lots = connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0]
        date_range = connection.execute("SELECT MIN(date(start_time)), MAX(date(COALESCE(complete_time, start_time))) FROM lots").fetchone()
        knowledge_chunks = connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
        historical_cases = connection.execute("SELECT COUNT(*) FROM historical_cases").fetchone()[0]
        process_runs = connection.execute("SELECT COUNT(*) FROM process_runs").fetchone()[0]
        sensor_readings = connection.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0]
        wafer_maps = connection.execute("SELECT COUNT(*) FROM wafer_maps").fetchone()[0]
    return {
        "status": "ok",
        "database": {"lots": lots, "process_runs": process_runs, "sensor_readings": sensor_readings, "wafer_maps": wafer_maps, "start": date_range[0], "end": date_range[1]},
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
        session = create_session(request.message[:50]) if not request.session_id else get_session(request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session_id = session["session_id"]
    history = session_history(session_id)
    append_message(session_id, "user", request.message)
    try:
        result = await run_agent(request.message, history or [item.model_dump() for item in request.history])
        result["session_id"] = session_id
        message = append_message(session_id, "assistant", result["answer"], result)
        record_agent_result(session_id, message["message_id"], result)
        return result
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


@app.post("/api/sessions")
def start_session() -> dict:
    return create_session()


@app.get("/api/sessions")
def session_list(
    q: str = Query("", max_length=100),
    limit: int = Query(100, ge=1, le=200),
    include_archived: bool = False,
) -> list[dict]:
    return list_sessions(q, limit, include_archived)


@app.patch("/api/sessions/{session_id}")
def update_session(session_id: str, request: SessionUpdateRequest) -> dict:
    try:
        return rename_session(session_id, request.title)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    try:
        return archive_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}")
def read_session(session_id: str) -> dict:
    try:
        return get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _stream_line(event_type: str, **payload) -> bytes:
    return (json.dumps({"type": event_type, **payload}, ensure_ascii=False, default=str) + "\n").encode("utf-8")


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    try:
        session = create_session(request.message[:50]) if not request.session_id else get_session(request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session_id = session["session_id"]
    history = session_history(session_id)
    append_message(session_id, "user", request.message)

    async def event_stream():
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def progress(event: dict) -> None:
            await queue.put(event)
            await asyncio.sleep(0)

        task = asyncio.create_task(run_agent(request.message, history, progress))
        yield _stream_line("session", session_id=session_id)
        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.25)
                except TimeoutError:
                    continue
                yield _stream_line("progress", **event)
            result = await task
            result["session_id"] = session_id
            message = append_message(session_id, "assistant", result["answer"], result)
            record_agent_result(session_id, message["message_id"], result)
            yield _stream_line("result", result=result)
        except asyncio.CancelledError:
            task.cancel()
            raise
        except httpx.HTTPStatusError as exc:
            detail = f"DeepSeek API 返回 {exc.response.status_code}"
            try:
                api_error = exc.response.json().get("error", {}).get("message")
                if api_error:
                    detail += f": {api_error}"
            except Exception:
                pass
            yield _stream_line("error", detail=detail)
        except httpx.RequestError as exc:
            yield _stream_line("error", detail=f"无法连接 DeepSeek API: {exc}")
        except Exception as exc:
            yield _stream_line("error", detail=f"分析失败: {exc}")
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/monitor/summary")
def monitor_summary(
    hours: int = Query(24, ge=1, le=720),
    recent_limit: int = Query(20, ge=1, le=100),
) -> dict:
    return monitoring_summary(hours, recent_limit)


@app.get("/api/monitor/events")
def monitor_events(limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    return list(reversed(read_events(limit)))
