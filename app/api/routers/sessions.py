from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..schemas import BulkSessionDeleteRequest, SessionUpdateRequest
from .runtime import NamespaceProvider, RouterBundle


def create_router(deps: NamespaceProvider) -> RouterBundle:
    def start_session() -> dict:
        return deps()["create_session"]()

    def session_list(
        q: str = Query("", max_length=100),
        limit: int = Query(100, ge=1, le=200),
        include_archived: bool = False,
    ) -> list[dict]:
        return deps()["list_sessions"](q, limit, include_archived)

    def update_session(session_id: str, request: SessionUpdateRequest) -> dict:
        try:
            return deps()["rename_session"](session_id, request.title)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def delete_session(session_id: str) -> dict:
        try:
            return deps()["archive_session"](session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def restore_archived_session(session_id: str) -> dict:
        try:
            return deps()["restore_session"](session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def permanently_delete_session(session_id: str) -> dict:
        try:
            return deps()["delete_session_permanently"](session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def bulk_delete_sessions(request: BulkSessionDeleteRequest) -> dict:
        return deps()["delete_sessions_permanently"](request.session_ids)

    def read_session(session_id: str) -> dict:
        try:
            return deps()["get_session"](session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def read_agent_run_audit(run_id: str) -> dict:
        try:
            return deps()["get_run_audit"](run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    router = APIRouter()
    router.add_api_route("/api/sessions", start_session, methods=["POST"])
    router.add_api_route("/api/sessions", session_list, methods=["GET"])
    router.add_api_route(
        "/api/sessions/bulk-delete", bulk_delete_sessions, methods=["POST"]
    )
    router.add_api_route(
        "/api/sessions/{session_id}", update_session, methods=["PATCH"]
    )
    router.add_api_route(
        "/api/sessions/{session_id}", delete_session, methods=["DELETE"]
    )
    router.add_api_route(
        "/api/sessions/{session_id}/restore", restore_archived_session, methods=["POST"]
    )
    router.add_api_route(
        "/api/sessions/{session_id}/permanent",
        permanently_delete_session,
        methods=["DELETE"],
    )
    router.add_api_route("/api/sessions/{session_id}", read_session, methods=["GET"])
    router.add_api_route(
        "/api/agent-runs/{run_id}/audit", read_agent_run_audit, methods=["GET"]
    )
    return RouterBundle(
        router,
        {
            "start_session": start_session,
            "session_list": session_list,
            "update_session": update_session,
            "delete_session": delete_session,
            "restore_archived_session": restore_archived_session,
            "permanently_delete_session": permanently_delete_session,
            "bulk_delete_sessions": bulk_delete_sessions,
            "read_session": read_session,
            "read_agent_run_audit": read_agent_run_audit,
        },
    )
