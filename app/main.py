from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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
from .api.runtime_dependencies import (
    MANUFACTURING_STEPS,
    PROJECT_DIR,
    ChatService,
    ChatStreamService,
    PersonalKnowledgeError,
    PrincipalContextMiddleware,
    RUNTIME_DEPENDENCIES,
    RequestAuditMiddleware,
    admin_router,
    chat_router,
    current_principal,
    current_request_id,
    db_session,
    emit,
    ensure_department_databases,
    ensure_model_catalog,
    enterprise_router,
    generate_database,
    get_settings,
    knowledge_router,
    models_router,
    monitor_router,
    pending_personal_jobs,
    process_personal_document,
    process_personal_document_deletion,
    recover_interrupted_executions,
    reports_router,
    seed_reference_data,
    sessions_router,
    system_router,
)


# Route and service factories obtain this module namespace on every call. Publish
# the original objects once so existing patch("app.main.<name>") call sites retain
# object identity and remain live for extracted implementations.
globals().update(RUNTIME_DEPENDENCIES)


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


def _publish_bundle(bundle) -> None:
    """Publish exact RouterBundle exports as ``app.main`` compatibility aliases."""
    globals().update(bundle.exports)


def _register_bundles(*bundles) -> None:
    for bundle in bundles:
        _include_domain_router(bundle.router)
        _publish_bundle(bundle)


_system_routes = system_router.create_router(_router_namespace)
_enterprise_routes = enterprise_router.create_router(_router_namespace)
_model_routes = models_router.create_router(_router_namespace)
_admin_routes = admin_router.create_router(_router_namespace, current_admin)
_report_routes = reports_router.create_router(_router_namespace)
_knowledge_routes = knowledge_router.create_router(
    _router_namespace, current_personal_user
)

_register_bundles(
    _system_routes,
    _enterprise_routes,
    _model_routes,
    _admin_routes,
    _report_routes,
    _knowledge_routes,
)


_chat_service = ChatService(_router_namespace)
_chat_stream_service = ChatStreamService(_router_namespace)
_chat_routes = chat_router.create_router(_router_namespace)
_include_domain_router(_chat_routes.router)
_publish_bundle(_chat_routes)
_prepare_chat = _chat_service.prepare_chat
_validate_chat_model_capabilities = _chat_service.validate_chat_model_capabilities
_model_status_error = _chat_service.model_status_error
_stream_line = _chat_stream_service.stream_line


_session_routes = sessions_router.create_router(_router_namespace)
_include_domain_router(_session_routes.router)
_publish_bundle(_session_routes)


_monitor_routes = monitor_router.create_router(_router_namespace, current_admin)
_include_domain_router(_monitor_routes.router)
_publish_bundle(_monitor_routes)
