from __future__ import annotations

import asyncio
import json
import os
import secrets
import traceback
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from .agent import run_agent
from .audit import GIT_COMMIT, current_request_id, emit, monitoring_summary, read_events
from .config import APP_VERSION, PROJECT_DIR, ModelConnection, get_settings
from .database import db_session, department_paths, ensure_department_databases
from .enterprise_data import EnterpriseDataError, get_enterprise_provider
from .execution_store import (
    RunExecutionRecorder,
    get_run_audit,
    recover_interrupted_executions,
)
from .identity import Principal, PrincipalContextMiddleware, current_principal
from .model_registry import (
    ensure_model_catalog,
    list_models,
    public_user_model_config,
    publish_model,
    save_model_compatibility_report,
    select_user_model,
    set_model_status,
    update_model_capabilities,
)
from .model_compatibility import ModelCompatibilityError, check_model_compatibility
from .processes import MANUFACTURING_STEPS, PROCESS_STEP_PATTERN
from .personal_knowledge import (
    PersonalDocumentPatch,
    PersonalKnowledgeError,
    begin_delete_personal_document,
    create_personal_upload,
    get_personal_chunk,
    get_personal_document,
    get_personal_job,
    list_personal_job_snapshots,
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
from .runtime_status import admin_runtime_overview, begin_agent_run, finish_agent_run
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
from .api.application import ApplicationDependencies, create_application, lifespan_for
from .api.dependencies import (
    AuthenticationDependencies,
    current_admin as _current_admin,
    current_personal_user as _current_personal_user,
)
from .api.errors import (
    ErrorDependencies,
    error_payload as _error_payload,
    handlers as _error_handlers,
    http_problem,
    personal_problem as _personal_problem,
)
from .api.schemas import (
    AdminModelCapabilitiesRequest,
    AdminModelPublishRequest,
    AdminModelStatusRequest,
    BulkSessionDeleteRequest,
    ChatMessage,
    ChatRequest,
    ModelCapabilitiesRequest,
    ModelConfigRequest,
    PersonalSearchPreviewRequest,
    SessionUpdateRequest,
    StreamTelemetryRequest,
)
from .api.services.personal_job_events import (
    PERSONAL_JOB_ACTIVE_STATUSES,
    encode_personal_job_event,
    iter_personal_job_events,
    personal_job_event_id,
    personal_job_snapshot_fingerprint,
    read_personal_job_snapshots,
)
from .api.routers import (
    admin as admin_router,
    enterprise as enterprise_router,
    knowledge as knowledge_router,
    models as models_router,
    monitor as monitor_router,
    reports as reports_router,
    sessions as sessions_router,
    system as system_router,
)


def _application_dependencies() -> ApplicationDependencies:
    return ApplicationDependencies(
        ensure_department_databases=ensure_department_databases,
        recover_interrupted_executions=recover_interrupted_executions,
        ensure_model_catalog=ensure_model_catalog,
        db_session=db_session,
        manufacturing_steps=MANUFACTURING_STEPS,
        generate_database=generate_database,
        seed_reference_data=seed_reference_data,
        pending_personal_jobs=pending_personal_jobs,
        process_personal_document=process_personal_document,
        process_personal_document_deletion=process_personal_document_deletion,
        to_thread=asyncio.to_thread,
    )


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    async with lifespan_for(_application_dependencies())(app_instance):
        yield


app = create_application(
    lifespan=lifespan,
    project_dir=PROJECT_DIR,
    principal_context_middleware=PrincipalContextMiddleware,
    request_audit_middleware=RequestAuditMiddleware,
)


def error_payload(
    error_code: str, detail: str, retryable: bool = False, **extra
) -> dict:
    return _error_payload(
        error_code,
        detail,
        retryable,
        deps=ErrorDependencies(current_request_id=current_request_id, emit=emit),
        **extra,
    )


@app.exception_handler(HTTPException)
async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
    handler, _, _ = _error_handlers(
        ErrorDependencies(current_request_id=current_request_id, emit=emit)
    )
    return await handler(_, exc)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    _, handler, _ = _error_handlers(
        ErrorDependencies(current_request_id=current_request_id, emit=emit)
    )
    return await handler(_, exc)


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    _, _, handler = _error_handlers(
        ErrorDependencies(current_request_id=current_request_id, emit=emit)
    )
    return await handler(_, exc)


def current_personal_user(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    return _current_personal_user(
        authorization,
        deps=AuthenticationDependencies(
            get_settings, current_principal, http_problem, secrets.compare_digest
        ),
    )


def current_admin(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    return _current_admin(
        authorization,
        deps=AuthenticationDependencies(
            get_settings, current_principal, http_problem, secrets.compare_digest
        ),
    )


def personal_problem(exc: PersonalKnowledgeError) -> HTTPException:
    return _personal_problem(exc)


_VERSIONED_PAGE_TEMPLATES = {
    "index": PROJECT_DIR / "app" / "static" / "index.html",
    "admin": PROJECT_DIR / "app" / "static" / "admin.html",
}


def _router_namespace():
    """Expose the live main namespace to extracted routes for patch compatibility."""
    return globals()


def _include_domain_router(router) -> None:
    """Include a router while retaining legacy concrete ``app.routes`` inspection."""
    before_count = len(app.router.routes)
    app.include_router(router)
    added = app.router.routes[before_count:]
    if len(added) == 1 and not hasattr(added[0], "path"):
        app.router.routes[before_count:] = router.routes


_system_routes = system_router.create_router(_router_namespace)
_enterprise_routes = enterprise_router.create_router(_router_namespace)
_model_routes = models_router.create_router(_router_namespace)
_admin_routes = admin_router.create_router(_router_namespace, current_admin)
_report_routes = reports_router.create_router(_router_namespace)
_knowledge_routes = knowledge_router.create_router(
    _router_namespace, current_personal_user
)

_include_domain_router(_system_routes.router)
_include_domain_router(_enterprise_routes.router)
_include_domain_router(_model_routes.router)
_include_domain_router(_admin_routes.router)
_include_domain_router(_report_routes.router)
_include_domain_router(_knowledge_routes.router)

render_versioned_page = _system_routes.exports["render_versioned_page"]
index = _system_routes.exports["index"]
admin_index = _system_routes.exports["admin_index"]
health = _system_routes.exports["health"]
version = _system_routes.exports["version"]
enterprise_context = _enterprise_routes.exports["enterprise_context"]
_enterprise_page = _enterprise_routes.exports["_enterprise_page"]
enterprise_manifest = _enterprise_routes.exports["enterprise_manifest"]
enterprise_summary = _enterprise_routes.exports["enterprise_summary"]
enterprise_lots = _enterprise_routes.exports["enterprise_lots"]
enterprise_process_runs = _enterprise_routes.exports["enterprise_process_runs"]
enterprise_sensor_events = _enterprise_routes.exports["enterprise_sensor_events"]
get_model_config = _model_routes.exports["get_model_config"]
set_model_config = _model_routes.exports["set_model_config"]
_compatibility_failure_report = _admin_routes.exports["_compatibility_failure_report"]
admin_overview = _admin_routes.exports["admin_overview"]
admin_models = _admin_routes.exports["admin_models"]
admin_publish_model = _admin_routes.exports["admin_publish_model"]
admin_update_model_status = _admin_routes.exports["admin_update_model_status"]
admin_update_model_capabilities = _admin_routes.exports[
    "admin_update_model_capabilities"
]
admin_check_model_compatibility = _admin_routes.exports[
    "admin_check_model_compatibility"
]
dashboard = _report_routes.exports["dashboard"]
capability = _report_routes.exports["capability"]
knowledge_documents = _knowledge_routes.exports["knowledge_documents"]
knowledge_document = _knowledge_routes.exports["knowledge_document"]
upload_personal_knowledge_document = _knowledge_routes.exports[
    "upload_personal_knowledge_document"
]
personal_knowledge_job_events = _knowledge_routes.exports[
    "personal_knowledge_job_events"
]
personal_knowledge_job = _knowledge_routes.exports["personal_knowledge_job"]
personal_knowledge_documents = _knowledge_routes.exports["personal_knowledge_documents"]
personal_knowledge_document = _knowledge_routes.exports["personal_knowledge_document"]
personal_knowledge_document_content = _knowledge_routes.exports[
    "personal_knowledge_document_content"
]
download_personal_knowledge_document = _knowledge_routes.exports[
    "download_personal_knowledge_document"
]
patch_personal_knowledge_document = _knowledge_routes.exports[
    "patch_personal_knowledge_document"
]
retry_personal_knowledge_document = _knowledge_routes.exports[
    "retry_personal_knowledge_document"
]
delete_personal_knowledge_document = _knowledge_routes.exports[
    "delete_personal_knowledge_document"
]
personal_knowledge_search_preview = _knowledge_routes.exports[
    "personal_knowledge_search_preview"
]
personal_knowledge_chunk = _knowledge_routes.exports["personal_knowledge_chunk"]
historical_cases = _knowledge_routes.exports["historical_cases"]
historical_case = _knowledge_routes.exports["historical_case"]
rag_search = _knowledge_routes.exports["rag_search"]


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    principal, selected_model = _validate_chat_model_capabilities(request)
    session_id, history, cached, user_message = _prepare_chat(request)
    if cached:
        cached["session_id"] = session_id
        cached["request_id"] = current_request_id()
        return cached
    recorder = RunExecutionRecorder(
        session_id,
        user_message["message_id"] if user_message else None,
        request.message,
        selected_model,
    )
    begin_agent_run(principal, session_id, request.message, selected_model)
    try:
        result = await run_agent(
            request.message,
            history or [item.model_dump() for item in request.history],
            recorder.observe,
            thinking=request.thinking,
            session_id=session_id,
            user_message_id=user_message["message_id"] if user_message else None,
        )
        recorder.complete(result)
        result["session_id"] = session_id
        result["request_id"] = current_request_id()
        result["client_message_id"] = request.client_message_id
        message = append_message(session_id, "assistant", result["answer"], result)
        record_agent_result(
            session_id,
            message["message_id"],
            result,
            user_message_id=user_message["message_id"] if user_message else None,
            question=request.message,
        )
        emit(
            "agent_run_persisted",
            str(result.get("run_id") or session_id),
            session_id=session_id,
            user_message_id=user_message["message_id"] if user_message else None,
            assistant_message_id=message["message_id"],
        )
        finish_agent_run(
            principal,
            "success",
            str(result.get("run_id") or ""),
            str(result.get("model") or selected_model),
        )
        return result
    except httpx.HTTPStatusError as exc:
        recorder.fail(str(exc))
        finish_agent_run(principal, "error", model=selected_model, error=str(exc))
        detail, retryable = _model_status_error(exc)
        raise http_problem(502, "MODEL_UPSTREAM_ERROR", detail, retryable) from exc
    except httpx.RequestError as exc:
        recorder.fail(str(exc))
        finish_agent_run(principal, "error", model=selected_model, error=str(exc))
        raise http_problem(
            502, "MODEL_NETWORK_ERROR", f"无法连接模型 API: {exc}", True
        ) from exc
    except Exception as exc:
        recorder.fail(str(exc))
        finish_agent_run(principal, "error", model=selected_model, error=str(exc))
        raise


_session_routes = sessions_router.create_router(_router_namespace)
_include_domain_router(_session_routes.router)

start_session = _session_routes.exports["start_session"]
session_list = _session_routes.exports["session_list"]
update_session = _session_routes.exports["update_session"]
delete_session = _session_routes.exports["delete_session"]
restore_archived_session = _session_routes.exports["restore_archived_session"]
permanently_delete_session = _session_routes.exports["permanently_delete_session"]
bulk_delete_sessions = _session_routes.exports["bulk_delete_sessions"]
read_session = _session_routes.exports["read_session"]
read_agent_run_audit = _session_routes.exports["read_agent_run_audit"]


def _stream_line(event_type: str, **payload) -> bytes:
    return (
        json.dumps({"type": event_type, **payload}, ensure_ascii=False, default=str)
        + "\n"
    ).encode("utf-8")


def _prepare_chat(
    request: ChatRequest,
) -> tuple[str, list[dict], dict | None, dict | None]:
    try:
        session = (
            create_session(request.message[:50])
            if not request.session_id
            else get_session(request.session_id)
        )
    except ValueError as exc:
        raise http_problem(404, "SESSION_NOT_FOUND", str(exc), False) from exc
    session_id = session["session_id"]
    existing_content = client_message_content(session_id, request.client_message_id)
    if existing_content is not None and existing_content != request.message:
        raise http_problem(
            409, "IDEMPOTENCY_CONFLICT", "同一客户端消息编号不能用于不同内容", False
        )
    cached = cached_agent_result(session_id, request.client_message_id)
    if cached:
        return session_id, [], cached, None
    history = session_history(session_id)
    user_message = append_message(
        session_id,
        "user",
        request.message,
        client_message_id=request.client_message_id,
    )
    if (
        user_message.get("duplicate")
        and history
        and history[-1].get("role") == "user"
        and history[-1].get("content") == request.message
    ):
        history = history[:-1]
    return session_id, history, None, user_message


def _validate_chat_model_capabilities(request: ChatRequest) -> tuple[Principal, str]:
    """Reject unsupported request modes before any session or run write."""
    principal = current_principal()
    config = public_user_model_config(principal)
    if request.thinking and not config["capabilities"].get("thinking", False):
        raise http_problem(
            400,
            "MODEL_CAPABILITY_UNSUPPORTED",
            "当前模型不支持 Thinking 请求",
            False,
        )
    return principal, config["model"]


def _model_status_error(exc: httpx.HTTPStatusError) -> tuple[str, bool]:
    status_code = exc.response.status_code
    detail = f"模型 API 返回 {status_code}"
    try:
        api_error = exc.response.json().get("error", {}).get("message")
        if api_error:
            detail += f": {str(api_error)[:300]}"
    except Exception:
        pass
    return detail, status_code == 429 or status_code >= 500


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    principal, selected_model = _validate_chat_model_capabilities(request)
    session_id, history, cached, user_message = _prepare_chat(request)
    recorder = RunExecutionRecorder(
        session_id,
        user_message["message_id"] if user_message else None,
        request.message,
        selected_model,
    )

    async def event_stream():
        yield _stream_line("session", session_id=session_id)
        if cached:
            cached["session_id"] = session_id
            cached["request_id"] = current_request_id()
            yield _stream_line("result", result=cached)
            return
        begin_agent_run(principal, session_id, request.message, selected_model)
        activity_finished = False
        queue: asyncio.Queue[tuple[dict, float]] = asyncio.Queue()
        stream_started = asyncio.get_running_loop().time()
        delivery = {
            "answer_events": 0,
            "answer_chars": 0,
            "first_answer_ms": None,
            "max_enqueue_gap_ms": 0.0,
            "max_queue_wait_ms": 0.0,
            "max_sse_gap_ms": 0.0,
        }
        last_answer_enqueued: float | None = None
        first_answer_yielded: float | None = None
        last_answer_yielded: float | None = None

        async def progress(event: dict) -> None:
            nonlocal last_answer_enqueued
            await recorder.observe(event)
            enqueued_at = asyncio.get_running_loop().time()
            if event.get("event") == "answer_delta":
                delivery["answer_events"] += 1
                delivery["answer_chars"] += len(str(event.get("delta") or ""))
                if last_answer_enqueued is None:
                    delivery["first_answer_ms"] = round(
                        (enqueued_at - stream_started) * 1000, 1
                    )
                else:
                    delivery["max_enqueue_gap_ms"] = max(
                        delivery["max_enqueue_gap_ms"],
                        round((enqueued_at - last_answer_enqueued) * 1000, 1),
                    )
                last_answer_enqueued = enqueued_at
            await queue.put((event, enqueued_at))
            await asyncio.sleep(0)

        task = asyncio.create_task(
            run_agent(
                request.message,
                history,
                progress,
                thinking=request.thinking,
                session_id=session_id,
                user_message_id=user_message["message_id"] if user_message else None,
            )
        )
        try:
            while not task.done() or not queue.empty():
                try:
                    event, enqueued_at = await asyncio.wait_for(
                        queue.get(), timeout=0.25
                    )
                except TimeoutError:
                    continue
                now = asyncio.get_running_loop().time()
                delivery["max_queue_wait_ms"] = max(
                    delivery["max_queue_wait_ms"], round((now - enqueued_at) * 1000, 1)
                )
                if event.get("event") == "answer_delta":
                    if first_answer_yielded is None:
                        first_answer_yielded = now
                    if last_answer_yielded is not None:
                        delivery["max_sse_gap_ms"] = max(
                            delivery["max_sse_gap_ms"],
                            round((now - last_answer_yielded) * 1000, 1),
                        )
                    last_answer_yielded = now
                yield _stream_line("progress", **event)
            result = await task
            delivery["duration_ms"] = round(
                (asyncio.get_running_loop().time() - stream_started) * 1000, 1
            )
            delivery["answer_stream_duration_ms"] = (
                round((last_answer_yielded - first_answer_yielded) * 1000, 1)
                if first_answer_yielded is not None and last_answer_yielded is not None
                else None
            )
            trace_semantics = result.setdefault(
                "trace_semantics", {"schema_version": "1.0"}
            )
            if isinstance(trace_semantics, dict):
                trace_semantics["stream_duration_ms"] = delivery[
                    "answer_stream_duration_ms"
                ]
            recorder.complete(result)
            result["session_id"] = session_id
            result["request_id"] = current_request_id()
            result["client_message_id"] = request.client_message_id
            message = append_message(session_id, "assistant", result["answer"], result)
            record_agent_result(
                session_id,
                message["message_id"],
                result,
                user_message_id=user_message["message_id"] if user_message else None,
                question=request.message,
            )
            emit(
                "agent_run_persisted",
                str(result.get("run_id") or session_id),
                session_id=session_id,
                user_message_id=user_message["message_id"] if user_message else None,
                assistant_message_id=message["message_id"],
            )
            finish_agent_run(
                principal,
                "success",
                str(result.get("run_id") or ""),
                str(result.get("model") or selected_model),
            )
            activity_finished = True
            emit(
                "stream_delivery_summary",
                str(result.get("run_id") or session_id),
                **delivery,
            )
            yield _stream_line(
                "progress",
                event="stream_delivery_summary",
                run_id=result.get("run_id"),
                **delivery,
            )
            yield _stream_line("result", result=result)
        except asyncio.CancelledError:
            task.cancel()
            recorder.fail("客户端已断开连接", interrupted=True)
            finish_agent_run(
                principal, "error", model=selected_model, error="客户端已断开连接"
            )
            activity_finished = True
            raise
        except httpx.HTTPStatusError as exc:
            recorder.fail(str(exc))
            finish_agent_run(principal, "error", model=selected_model, error=str(exc))
            activity_finished = True
            detail, retryable = _model_status_error(exc)
            problem = error_payload("MODEL_UPSTREAM_ERROR", detail, retryable)
            emit(
                "api_stream_error",
                current_request_id() or session_id,
                status="error",
                error_type="MODEL_UPSTREAM_ERROR",
                session_id=session_id,
                retryable=retryable,
            )
            yield _stream_line("error", detail=detail, error=problem)
        except httpx.RequestError as exc:
            recorder.fail(str(exc))
            finish_agent_run(principal, "error", model=selected_model, error=str(exc))
            activity_finished = True
            detail = f"无法连接模型 API: {exc}"
            emit(
                "api_stream_error",
                current_request_id() or session_id,
                status="error",
                error_type="MODEL_NETWORK_ERROR",
                session_id=session_id,
                retryable=True,
            )
            yield _stream_line(
                "error",
                detail=detail,
                error=error_payload("MODEL_NETWORK_ERROR", detail, True),
            )
        except Exception as exc:
            recorder.fail(str(exc))
            finish_agent_run(principal, "error", model=selected_model, error=str(exc))
            activity_finished = True
            detail = f"分析失败: {exc}"
            emit(
                "api_stream_error",
                current_request_id() or session_id,
                status="error",
                error_type=type(exc).__name__,
                session_id=session_id,
                retryable=False,
                full_content={
                    "error_message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            yield _stream_line(
                "error",
                detail=detail,
                error=error_payload("ANALYSIS_ERROR", detail, False),
            )
        finally:
            if not task.done():
                task.cancel()
            if not activity_finished:
                finish_agent_run(
                    principal,
                    "error",
                    model=selected_model,
                    error="Agent 运行未正常完成",
                )

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


_monitor_routes = monitor_router.create_router(_router_namespace, current_admin)
_include_domain_router(_monitor_routes.router)
record_stream_telemetry = _monitor_routes.exports["record_stream_telemetry"]
monitor_summary = _monitor_routes.exports["monitor_summary"]
monitor_events = _monitor_routes.exports["monitor_events"]
