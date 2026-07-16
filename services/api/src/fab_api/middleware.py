from __future__ import annotations

import contextvars
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("fab_api_request_id", default=None)


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])
        }
        candidate = headers.get("x-request-id", "")
        request_id = (
            candidate
            if 8 <= len(candidate) <= 64 and candidate.replace("-", "").replace("_", "").isalnum()
            else f"req-{uuid.uuid4()}"
        )
        token = REQUEST_ID.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            REQUEST_ID.reset(token)


def current_request_id() -> str:
    return REQUEST_ID.get() or f"req-{uuid.uuid4()}"
