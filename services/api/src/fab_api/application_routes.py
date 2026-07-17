from collections.abc import Callable
from typing import Annotated, Any

from fab_agent import FabAnalysisAgent
from fab_contracts import ApiEnvelope, IdentityContext
from fab_core import DomainError
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, SecretStr

from .middleware import current_request_id
from .monitoring import AuditReader
from .repositories import KnowledgeRepository, SessionRepository


class SessionCreate(BaseModel):
    title: str = Field(default="新会话", max_length=80)


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=8_000)
    session_id: str | None = None


class ModelConfigUpdate(BaseModel):
    model: str = Field(min_length=2, max_length=100)
    api_key: SecretStr | None = None


def build_application_router(
    knowledge: KnowledgeRepository,
    sessions: SessionRepository,
    audit: AuditReader,
    agent: FabAnalysisAgent,
    identity: Callable[..., IdentityContext],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    current_identity = Annotated[IdentityContext, Depends(identity)]

    def require_admin(current: IdentityContext) -> None:
        if "admin" not in current.roles:
            raise DomainError(
                "ADMIN_REQUIRED",
                "administrator credentials are required",
                status_code=403,
            )

    @router.get("/knowledge/documents")
    def knowledge_documents(_: current_identity) -> ApiEnvelope[list[dict[str, Any]]]:
        return ApiEnvelope(data=knowledge.list_documents(), request_id=current_request_id())

    @router.get("/knowledge/chunks/{chunk_id}")
    def knowledge_document(chunk_id: int, _: current_identity) -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(data=knowledge.get_document(chunk_id), request_id=current_request_id())

    @router.get("/cases")
    def cases(_: current_identity) -> ApiEnvelope[list[dict[str, Any]]]:
        return ApiEnvelope(data=knowledge.list_cases(), request_id=current_request_id())

    @router.get("/cases/{case_id}")
    def case(case_id: str, _: current_identity) -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(data=knowledge.get_case(case_id), request_id=current_request_id())

    @router.post("/sessions", status_code=201)
    def create_session(payload: SessionCreate, _: current_identity) -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(data=sessions.create(payload.title), request_id=current_request_id())

    @router.get("/sessions")
    def list_sessions(
        _: current_identity,
        query: str = Query("", max_length=100),
        include_archived: bool = False,
        limit: int = Query(100, ge=1, le=200),
    ) -> ApiEnvelope[list[dict[str, Any]]]:
        return ApiEnvelope(
            data=sessions.list(query, limit, include_archived), request_id=current_request_id()
        )

    @router.get("/sessions/{session_id}")
    def get_session(session_id: str, _: current_identity) -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(data=sessions.get(session_id), request_id=current_request_id())

    @router.patch("/sessions/{session_id}")
    def rename_session(
        session_id: str, payload: SessionUpdate, _: current_identity
    ) -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(data=sessions.rename(session_id, payload.title), request_id=current_request_id())

    @router.delete("/sessions/{session_id}")
    def archive_session(session_id: str, _: current_identity) -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(data=sessions.set_archived(session_id, True), request_id=current_request_id())

    @router.post("/sessions/{session_id}/restore")
    def restore_session(session_id: str, _: current_identity) -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(data=sessions.set_archived(session_id, False), request_id=current_request_id())

    @router.delete("/sessions/{session_id}/permanent")
    def delete_session(session_id: str, _: current_identity) -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(data=sessions.delete(session_id), request_id=current_request_id())

    @router.get("/settings/model/current")
    def get_current_model(_: current_identity) -> ApiEnvelope[dict[str, str]]:
        config = agent.public_model_config()
        model = str(config["model"]) if config["api_key_configured"] else "local-rules"
        return ApiEnvelope(data={"model": model}, request_id=current_request_id())

    @router.get("/admin/settings/model")
    def get_model_config(current: current_identity) -> ApiEnvelope[dict[str, Any]]:
        require_admin(current)
        return ApiEnvelope(data=agent.public_model_config(), request_id=current_request_id())

    @router.post("/admin/settings/model")
    def update_model_config(
        payload: ModelConfigUpdate, current: current_identity
    ) -> ApiEnvelope[dict[str, Any]]:
        require_admin(current)
        api_key = payload.api_key.get_secret_value() if payload.api_key is not None else None
        try:
            data = agent.configure_model(payload.model, api_key)
        except ValueError as exc:
            raise DomainError("INVALID_MODEL_CONFIG", str(exc), status_code=422) from exc
        return ApiEnvelope(data=data, request_id=current_request_id())

    @router.post("/chat")
    async def chat(payload: ChatRequest, current: current_identity) -> ApiEnvelope[dict[str, Any]]:
        session_id = payload.session_id
        if session_id is None:
            session_id = sessions.create()["session_id"]
            history: list[dict[str, str]] = []
        else:
            session = sessions.get(session_id)
            history = [
                {"role": item["role"], "content": item["content"]} for item in session["messages"][-10:]
            ]
        sessions.append_message(session_id, "user", payload.message)
        result = await agent.analyze(payload.message, current, history)
        model_config = agent.public_model_config()
        assistant = sessions.append_message(
            session_id,
            "assistant",
            str(result["answer"]),
            {
                "mode": result["mode"],
                "tool_trace": result["tool_trace"],
                "sources": result.get("sources", []),
            },
            model=str(model_config["model"]) if model_config["api_key_configured"] else "local-rules",
        )
        return ApiEnvelope(
            data={**result, "session_id": session_id, "message_id": assistant["message_id"]},
            request_id=current_request_id(),
        )

    @router.get("/monitor/summary")
    def monitor_summary(
        current: current_identity, hours: int = Query(24, ge=1, le=720)
    ) -> ApiEnvelope[dict[str, Any]]:
        require_admin(current)
        return ApiEnvelope(data=audit.summary(hours), request_id=current_request_id())

    @router.get("/monitor/events")
    def monitor_events(
        current: current_identity, limit: int = Query(100, ge=1, le=1000)
    ) -> ApiEnvelope[list[dict[str, Any]]]:
        require_admin(current)
        return ApiEnvelope(data=audit.events(limit), request_id=current_request_id())

    return router
