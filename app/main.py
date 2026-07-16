from __future__ import annotations

import asyncio
import json
import secrets
import traceback
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from starlette.concurrency import run_in_threadpool

from .agent import run_agent
from .audit import CONTENT_MODE, GIT_COMMIT, current_request_id, emit, monitoring_summary, read_events
from .config import APP_VERSION, PROJECT_DIR, get_settings, public_model_config, update_model_config
from .database import db_session, department_paths, ensure_department_databases
from .processes import MANUFACTURING_STEPS, PROCESS_STEP_PATTERN
from .personal_knowledge import (
    PersonalDocumentPatch,
    PersonalKnowledgeError,
    begin_delete_personal_document,
    create_personal_upload,
    get_personal_chunk,
    get_personal_document,
    get_personal_job,
    list_personal_documents,
    pending_personal_jobs,
    personal_document_file,
    process_personal_document,
    process_personal_document_deletion,
    retry_personal_document,
    search_personal_knowledge,
    update_personal_document,
)
from .observability import RequestAuditMiddleware
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
    cached_agent_result,
    client_message_content,
    create_session,
    delete_session_permanently,
    delete_sessions_permanently,
    get_session,
    list_sessions,
    record_agent_result,
    rename_session,
    restore_session,
    session_history,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_department_databases()
    with db_session() as connection:
        populated_steps = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT process_step FROM process_runs WHERE measurement_value IS NOT NULL"
            )
        }
        has_sensor_data = bool(
            connection.execute("SELECT EXISTS(SELECT 1 FROM sensor_readings LIMIT 1)").fetchone()[0]
        )
        max_operation = connection.execute("SELECT MAX(operation_seq) FROM process_runs").fetchone()[0] or 0
        knowledge_count = connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
    if not set(MANUFACTURING_STEPS).issubset(populated_steps) or not has_sensor_data or max_operation < 18:
        generate_database()
    elif knowledge_count == 0:
        seed_reference_data()
    for document_id, owner_user_id, job_id, status in pending_personal_jobs():
        worker = process_personal_document_deletion if status == "deleting" else process_personal_document
        await asyncio.to_thread(worker, document_id, owner_user_id, job_id)
    yield


app = FastAPI(
    title="Fab Insight Agent",
    version="1.0.0",
    description="虚拟半导体制造报表、RAG 与数据分析 Agent",
    lifespan=lifespan,
)
app.add_middleware(RequestAuditMiddleware)
app.mount("/static", StaticFiles(directory=PROJECT_DIR / "app" / "static"), name="static")


def error_payload(error_code: str, detail: str, retryable: bool = False, **extra) -> dict:
    return {
        "error_code": error_code,
        "detail": detail,
        "request_id": current_request_id(),
        "retryable": retryable,
        **extra,
    }


def http_problem(status_code: int, error_code: str, detail: str, retryable: bool = False) -> HTTPException:
    return HTTPException(status_code=status_code, detail={
        "error_code": error_code,
        "message": detail,
        "retryable": retryable,
    })


@app.exception_handler(HTTPException)
async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        detail = str(exc.detail.get("message") or "请求失败")
        error_code = str(exc.detail.get("error_code") or "HTTP_ERROR")
        retryable = bool(exc.detail.get("retryable", exc.status_code >= 500))
    else:
        detail = str(exc.detail)
        error_code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        retryable = exc.status_code >= 500
    return JSONResponse(status_code=exc.status_code, content=error_payload(error_code, detail, retryable), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [".".join(str(part) for part in item.get("loc", [])[1:]) for item in exc.errors()]
    return JSONResponse(
        status_code=422,
        content=error_payload("VALIDATION_ERROR", "请求参数不符合要求", False, fields=[field for field in fields if field]),
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    request_id = current_request_id() or f"error-{uuid.uuid4()}"
    emit(
        "api_exception",
        request_id,
        status="error",
        error_type=type(exc).__name__,
        **({"error_message": str(exc), "traceback": traceback.format_exc()} if CONTENT_MODE == "full" else {}),
    )
    return JSONResponse(status_code=500, content=error_payload("INTERNAL_ERROR", "服务器内部错误", True))


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    session_id: str | None = None
    client_message_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ModelConfigRequest(BaseModel):
    model: str
    api_key: SecretStr | None = None


class SessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class BulkSessionDeleteRequest(BaseModel):
    session_ids: list[str] = Field(min_length=1, max_length=200)


class PersonalSearchPreviewRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=20)
    document_ids: list[str] = Field(default_factory=list, max_length=100)


def current_personal_user(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    settings = get_settings()
    configured_token = settings.personal_knowledge_api_token
    if configured_token:
        scheme, _, provided_token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(provided_token, configured_token):
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "AUTHENTICATION_REQUIRED",
                    "message": "个人知识库访问令牌无效",
                    "retryable": False,
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
    return settings.personal_knowledge_user_id


def personal_problem(exc: PersonalKnowledgeError) -> HTTPException:
    return http_problem(exc.status_code, exc.error_code, exc.detail, exc.retryable)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(
        PROJECT_DIR / "app" / "static" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    department_names = {"main": "manufacturing"}
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
        "database_departments": {
            department_names.get(name, name): {
                "path": str(path),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }
            for name, path in department_paths().items()
        },
        "model": settings.deepseek_model,
        "agent_configured": bool(settings.deepseek_api_key),
        "build": {"version": APP_VERSION, "git_commit": GIT_COMMIT},
        "reference_data": {"knowledge_chunks": knowledge_chunks, "historical_cases": historical_cases},
    }


@app.get("/api/version")
def version() -> dict:
    return {"version": APP_VERSION, "git_commit": GIT_COMMIT}


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


@app.post("/api/knowledge/personal/documents", status_code=202)
async def upload_personal_knowledge_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    owner_user_id: Annotated[str, Depends(current_personal_user)],
    metadata: Annotated[str | None, Form()] = None,
) -> dict:
    settings = get_settings()
    try:
        data = await file.read(settings.personal_knowledge_max_upload_bytes + 1)
        result = await run_in_threadpool(
            create_personal_upload,
            owner_user_id,
            file.filename,
            data,
            metadata,
            idempotency_key,
        )
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc
    finally:
        await file.close()
    if result.pop("_start_processing", False):
        background_tasks.add_task(
            process_personal_document,
            result["document_id"],
            owner_user_id,
            result["job_id"],
        )
    return result


@app.get("/api/knowledge/jobs/{job_id}")
def personal_knowledge_job(
    job_id: str,
    owner_user_id: Annotated[str, Depends(current_personal_user)],
) -> dict:
    try:
        return get_personal_job(job_id, owner_user_id)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc


@app.get("/api/knowledge/personal/documents")
def personal_knowledge_documents(
    owner_user_id: Annotated[str, Depends(current_personal_user)],
    q: str = Query("", max_length=100),
    status: str | None = Query(None, pattern=r"^(uploaded|parsing|chunking|indexing|ready|failed|deleting)$"),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=500),
) -> dict:
    try:
        return list_personal_documents(owner_user_id, q, status, limit, cursor)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc


@app.get("/api/knowledge/personal/documents/{document_id}")
def personal_knowledge_document(
    document_id: str,
    owner_user_id: Annotated[str, Depends(current_personal_user)],
) -> dict:
    try:
        return get_personal_document(document_id, owner_user_id)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc


@app.get("/api/knowledge/personal/documents/{document_id}/content")
def personal_knowledge_document_content(
    document_id: str,
    owner_user_id: Annotated[str, Depends(current_personal_user)],
) -> dict:
    try:
        return get_personal_document(document_id, owner_user_id, include_chunks=True)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc


@app.get("/api/knowledge/personal/documents/{document_id}/file")
def download_personal_knowledge_document(
    document_id: str,
    owner_user_id: Annotated[str, Depends(current_personal_user)],
):
    try:
        path, filename, mime_type = personal_document_file(document_id, owner_user_id)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc
    return FileResponse(path, media_type=mime_type, filename=filename)


@app.patch("/api/knowledge/personal/documents/{document_id}")
def patch_personal_knowledge_document(
    document_id: str,
    request: PersonalDocumentPatch,
    owner_user_id: Annotated[str, Depends(current_personal_user)],
) -> dict:
    try:
        return update_personal_document(document_id, owner_user_id, request)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc


@app.post("/api/knowledge/personal/documents/{document_id}/retry", status_code=202)
def retry_personal_knowledge_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    owner_user_id: Annotated[str, Depends(current_personal_user)],
) -> dict:
    try:
        result = retry_personal_document(document_id, owner_user_id)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc
    background_tasks.add_task(process_personal_document, document_id, owner_user_id, result["job_id"])
    return result


@app.delete("/api/knowledge/personal/documents/{document_id}", status_code=202)
def delete_personal_knowledge_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    owner_user_id: Annotated[str, Depends(current_personal_user)],
) -> dict:
    try:
        result = begin_delete_personal_document(document_id, owner_user_id)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc
    background_tasks.add_task(process_personal_document_deletion, document_id, owner_user_id, result["job_id"])
    return result


@app.post("/api/knowledge/personal/search-preview")
def personal_knowledge_search_preview(
    request: PersonalSearchPreviewRequest,
    owner_user_id: Annotated[str, Depends(current_personal_user)],
) -> dict:
    try:
        results = search_personal_knowledge(owner_user_id, request.query, request.limit, request.document_ids)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc
    return {"query": request.query, "count": len(results), "results": results}


@app.get("/api/knowledge/personal/chunks/{chunk_id}")
def personal_knowledge_chunk(
    chunk_id: str,
    owner_user_id: Annotated[str, Depends(current_personal_user)],
) -> dict:
    try:
        return get_personal_chunk(chunk_id, owner_user_id)
    except PersonalKnowledgeError as exc:
        raise personal_problem(exc) from exc


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
    session_id, history, cached = _prepare_chat(request)
    if cached:
        cached["session_id"] = session_id
        cached["request_id"] = current_request_id()
        return cached
    try:
        result = await run_agent(request.message, history or [item.model_dump() for item in request.history])
        result["session_id"] = session_id
        result["request_id"] = current_request_id()
        result["client_message_id"] = request.client_message_id
        message = append_message(session_id, "assistant", result["answer"], result)
        record_agent_result(session_id, message["message_id"], result)
        return result
    except httpx.HTTPStatusError as exc:
        detail, retryable = _model_status_error(exc)
        raise http_problem(502, "MODEL_UPSTREAM_ERROR", detail, retryable) from exc
    except httpx.RequestError as exc:
        raise http_problem(502, "MODEL_NETWORK_ERROR", f"无法连接 DeepSeek API: {exc}", True) from exc


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


@app.post("/api/sessions/{session_id}/restore")
def restore_archived_session(session_id: str) -> dict:
    try:
        return restore_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/sessions/{session_id}/permanent")
def permanently_delete_session(session_id: str) -> dict:
    try:
        return delete_session_permanently(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/sessions/bulk-delete")
def bulk_delete_sessions(request: BulkSessionDeleteRequest) -> dict:
    return delete_sessions_permanently(request.session_ids)


@app.get("/api/sessions/{session_id}")
def read_session(session_id: str) -> dict:
    try:
        return get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _stream_line(event_type: str, **payload) -> bytes:
    return (json.dumps({"type": event_type, **payload}, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def _prepare_chat(request: ChatRequest) -> tuple[str, list[dict], dict | None]:
    try:
        session = create_session(request.message[:50]) if not request.session_id else get_session(request.session_id)
    except ValueError as exc:
        raise http_problem(404, "SESSION_NOT_FOUND", str(exc), False) from exc
    session_id = session["session_id"]
    existing_content = client_message_content(session_id, request.client_message_id)
    if existing_content is not None and existing_content != request.message:
        raise http_problem(409, "IDEMPOTENCY_CONFLICT", "同一客户端消息编号不能用于不同内容", False)
    cached = cached_agent_result(session_id, request.client_message_id)
    if cached:
        return session_id, [], cached
    history = session_history(session_id)
    user_message = append_message(
        session_id,
        "user",
        request.message,
        client_message_id=request.client_message_id,
    )
    if user_message.get("duplicate") and history and history[-1].get("role") == "user" and history[-1].get("content") == request.message:
        history = history[:-1]
    return session_id, history, None


def _model_status_error(exc: httpx.HTTPStatusError) -> tuple[str, bool]:
    status_code = exc.response.status_code
    detail = f"DeepSeek API 返回 {status_code}"
    try:
        api_error = exc.response.json().get("error", {}).get("message")
        if api_error:
            detail += f": {str(api_error)[:300]}"
    except Exception:
        pass
    return detail, status_code == 429 or status_code >= 500


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    session_id, history, cached = _prepare_chat(request)

    async def event_stream():
        yield _stream_line("session", session_id=session_id)
        if cached:
            cached["session_id"] = session_id
            cached["request_id"] = current_request_id()
            yield _stream_line("result", result=cached)
            return
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def progress(event: dict) -> None:
            await queue.put(event)
            await asyncio.sleep(0)

        task = asyncio.create_task(run_agent(request.message, history, progress))
        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.25)
                except TimeoutError:
                    continue
                yield _stream_line("progress", **event)
            result = await task
            result["session_id"] = session_id
            result["request_id"] = current_request_id()
            result["client_message_id"] = request.client_message_id
            message = append_message(session_id, "assistant", result["answer"], result)
            record_agent_result(session_id, message["message_id"], result)
            yield _stream_line("result", result=result)
        except asyncio.CancelledError:
            task.cancel()
            raise
        except httpx.HTTPStatusError as exc:
            detail, retryable = _model_status_error(exc)
            problem = error_payload("MODEL_UPSTREAM_ERROR", detail, retryable)
            emit("api_stream_error", current_request_id() or session_id, status="error", error_type="MODEL_UPSTREAM_ERROR", session_id=session_id, retryable=retryable)
            yield _stream_line("error", detail=detail, error=problem)
        except httpx.RequestError as exc:
            detail = f"无法连接 DeepSeek API: {exc}"
            emit("api_stream_error", current_request_id() or session_id, status="error", error_type="MODEL_NETWORK_ERROR", session_id=session_id, retryable=True)
            yield _stream_line("error", detail=detail, error=error_payload("MODEL_NETWORK_ERROR", detail, True))
        except Exception as exc:
            detail = f"分析失败: {exc}"
            emit(
                "api_stream_error",
                current_request_id() or session_id,
                status="error",
                error_type=type(exc).__name__,
                session_id=session_id,
                retryable=False,
                **({"error_message": str(exc), "traceback": traceback.format_exc()} if CONTENT_MODE == "full" else {}),
            )
            yield _stream_line("error", detail=detail, error=error_payload("ANALYSIS_ERROR", detail, False))
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
