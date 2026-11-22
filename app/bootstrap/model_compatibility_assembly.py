"""Full compatibility check used by the application's model publication flow."""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..memory_system.context.history import build_contextualizer_messages
from ..memory_system.context.protocol import (
    CONTEXTUALIZER_RESPONSE_FORMAT,
    ContextPayloadValidationError,
    validate_contextualizer_payload,
)
from ..model_gateway.compatibility import ModelCompatibilityError, ProbeSender, check_model_transport


async def _check_structured_context(send: ProbeSender) -> str:
    response = await send({
        "messages": build_contextualizer_messages(
            "请将当前问题作为独立问题返回。",
            [
                {"message_id": 1, "role": "user", "content": "介绍光刻基本原理"},
                {"message_id": 2, "role": "assistant", "content": "已完成介绍。"},
            ],
        ),
        "temperature": 0,
        "response_format": CONTEXTUALIZER_RESPONSE_FORMAT,
        "max_tokens": 1200,
    })
    try:
        validate_contextualizer_payload(json.loads(response["content"]))
    except (TypeError, ValueError, ContextPayloadValidationError) as exc:
        raise ModelCompatibilityError("结构化上下文契约未通过", False, "structured_context") from exc
    return "structured_context"


async def check_model_compatibility(
    connection: Any,
    capabilities: dict,
    *,
    timeout_seconds: float | None = None,
    context_chars: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    return await check_model_transport(
        connection, capabilities, timeout_seconds=timeout_seconds, context_chars=context_chars,
        client=client, application_probe=_check_structured_context,
    )
