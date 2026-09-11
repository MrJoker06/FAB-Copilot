from __future__ import annotations

import json
import re
import time
import traceback
import uuid
from typing import Any
from urllib.parse import unquote

from .audit import emit, log_content_policy, reset_request_id, set_request_id
from ..config import get_settings


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MAX_AUDIT_BODY_BYTES = 64 * 1024


def new_request_id(candidate: str | None = None) -> str:
    cleaned = (candidate or "").strip()
    return cleaned if REQUEST_ID_PATTERN.fullmatch(cleaned) else f"req-{uuid.uuid4()}"


def _decode_body(body: bytes, content_type: str) -> Any:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    if "json" in content_type:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


class RequestAuditMiddleware:
    """Attach a correlation ID and audit the complete lifecycle of API requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        settings = get_settings()
        tenant_id = headers.get("x-tenant-id") or settings.enterprise_default_tenant_id
        user_id = headers.get("x-user-id") or settings.enterprise_default_user_id
        request_id = new_request_id(headers.get("x-request-id"))
        token = set_request_id(request_id)
        method = scope.get("method", "GET")
        path = scope.get("path", "")
        query = unquote(scope.get("query_string", b"").decode("latin-1"))
        capture_body = log_content_policy()["effective_mode"] == "full" and "multipart/form-data" not in headers.get("content-type", "")
        started = time.perf_counter()
        body_parts: list[bytes] = []
        status_code = 500
        response_started = False
        completed = False

        emit(
            "api_request_started",
            request_id,
            method=method,
            path=path,
            query=query,
            client=scope.get("client"),
            tenant_id=tenant_id,
            user_id=user_id,
            full_content={"headers": headers},
        )

        async def audited_receive():
            message = await receive()
            if capture_body and message.get("type") == "http.request" and len(b"".join(body_parts)) < MAX_AUDIT_BODY_BYTES:
                remaining = MAX_AUDIT_BODY_BYTES - sum(len(part) for part in body_parts)
                body_parts.append(message.get("body", b"")[:remaining])
            return message

        async def audited_send(message):
            nonlocal status_code, response_started, completed
            if message.get("type") == "http.response.start":
                response_started = True
                status_code = int(message.get("status", 500))
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = response_headers
            if message.get("type") == "http.response.body" and not message.get("more_body", False):
                completed = True
                emit(
                    "api_request_finished",
                    request_id,
                    status="success" if status_code < 400 else "error",
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    **({"error_type": f"HTTP_{status_code}"} if status_code >= 400 else {}),
                    full_content=({"request_body": _decode_body(b"".join(body_parts), headers.get("content-type", ""))} if body_parts else None),
                )
            await send(message)

        try:
            await self.app(scope, audited_receive, audited_send)
        except Exception as exc:
            if not completed:
                emit(
                    "api_exception",
                    request_id,
                    status="error",
                    method=method,
                    path=path,
                    error_type=type(exc).__name__,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
                )
                emit(
                    "api_request_finished",
                    request_id,
                    status="error",
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                    error_type=type(exc).__name__,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    full_content={"error_message": str(exc), "traceback": traceback.format_exc()},
                )
            if response_started:
                raise
            payload = json.dumps({
                "error_code": "INTERNAL_ERROR",
                "detail": "服务器内部错误",
                "request_id": request_id,
                "retryable": True,
            }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(payload)).encode("ascii")),
                    (b"x-request-id", request_id.encode("ascii")),
                ],
            })
            await send({"type": "http.response.body", "body": payload})
        finally:
            reset_request_id(token)
