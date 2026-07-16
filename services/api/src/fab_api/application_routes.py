from collections.abc import Callable
from typing import Annotated, Any

from fab_agent import FabAnalysisAgent
from fab_contracts import ApiEnvelope, IdentityContext
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

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


def build_application_router(
    knowledge: KnowledgeRepository,
    sessions: SessionRepository,
    audit: AuditReader,
    agent: FabAnalysisAgent,
    identity: Callable[..., IdentityContext],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    current_identity = Annotated[IdentityContext, Depends(identity)]

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

    @router.post("/chat")
    async def chat(payload: ChatRequest, current: current_identity) -> ApiEnvelope[dict[str, Any]]:
        session_id = payload.session_id
        if session_id is None:
            session_id = sessions.create()["session_id"]
        sessions.append_message(session_id, "user", payload.message)
        result = await agent.analyze(payload.message, current)
        assistant = sessions.append_message(
            session_id,
            "assistant",
            str(result["answer"]),
            {"mode": result["mode"], "tool_trace": result["tool_trace"]},
        )
        return ApiEnvelope(
            data={**result, "session_id": session_id, "message_id": assistant["message_id"]},
            request_id=current_request_id(),
        )

    @router.get("/monitor/summary")
    def monitor_summary(
        _: current_identity, hours: int = Query(24, ge=1, le=720)
    ) -> ApiEnvelope[dict[str, Any]]:
        return ApiEnvelope(data=audit.summary(hours), request_id=current_request_id())

    @router.get("/monitor/events")
    def monitor_events(
        _: current_identity, limit: int = Query(100, ge=1, le=1000)
    ) -> ApiEnvelope[list[dict[str, Any]]]:
        return ApiEnvelope(data=audit.events(limit), request_id=current_request_id())

    return router
