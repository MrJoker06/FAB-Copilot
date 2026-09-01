from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..schemas import ChatRequest
from .runtime import NamespaceProvider, RouterBundle


def create_router(deps: NamespaceProvider) -> RouterBundle:
    async def chat(request: ChatRequest) -> dict:
        return await deps()["_chat_service"].chat(request)

    async def chat_stream(request: ChatRequest) -> StreamingResponse:
        return deps()["_chat_stream_service"].chat_stream(request)

    router = APIRouter()
    router.add_api_route("/api/chat", chat, methods=["POST"])
    router.add_api_route("/api/chat/stream", chat_stream, methods=["POST"])
    return RouterBundle(router, {"chat": chat, "chat_stream": chat_stream})
