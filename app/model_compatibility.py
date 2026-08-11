"""Bounded, pre-publication checks for the runtime chat-completions contract."""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


MAX_SSE_EVENTS = 256
MAX_SSE_BYTES = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_CONTEXT_CHARS = 32768


@dataclass
class ModelCompatibilityError(ValueError):
    summary: str
    retryable: bool = False
    category: str = "protocol"

    def __str__(self) -> str:
        return self.summary


def provider_request_options(provider: str, thinking: bool = False) -> dict:
    """The only provider-specific request options used by runtime and probes."""
    if provider == "deepseek":
        return {"thinking": {"type": "enabled" if thinking else "disabled"}} if not thinking else {
            "thinking": {"type": "enabled"}, "reasoning_effort": "high"
        }
    return {"reasoning_effort": "high"} if thinking else {}


def compatibility_limits(timeout_seconds: float | None, context_chars: int | None) -> tuple[float, int]:
    try:
        timeout = float(os.getenv("MODEL_COMPATIBILITY_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))) if timeout_seconds is None else float(timeout_seconds)
        context = int(os.getenv("MODEL_COMPATIBILITY_CONTEXT_CHARS", str(DEFAULT_CONTEXT_CHARS))) if context_chars is None else int(context_chars)
    except (TypeError, ValueError) as exc:
        raise ModelCompatibilityError("兼容性检查配置格式无效", False, "configuration") from exc
    if not math.isfinite(timeout):
        raise ModelCompatibilityError("兼容性检查超时配置无效", False, "configuration")
    return max(1.0, min(timeout, 60.0)), max(1024, min(context, 65536))


async def _stream_probe(client: httpx.AsyncClient, endpoint: str, headers: dict, payload: dict) -> dict:
    saw_done = False
    content: list[str] = []
    tool_calls: dict[int, dict] = {}
    reasoning: list[str] = []
    event_count = byte_count = 0
    try:
        async with client.stream("POST", endpoint, headers=headers, json={**payload, "stream": True}) as response:
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", "").lower():
                raise ModelCompatibilityError("模型响应不是 SSE 事件流", False, "content_type")
            async for raw in response.aiter_lines():
                event_count += 1; byte_count += len(raw.encode("utf-8", "replace"))
                if event_count > MAX_SSE_EVENTS or byte_count > MAX_SSE_BYTES:
                    raise ModelCompatibilityError("模型 SSE 响应超过安全上限", False, "response_limit")
                line = raw.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    saw_done = True
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ModelCompatibilityError("模型返回了不合法的 SSE JSON", False, "malformed_sse") from exc
                if not isinstance(chunk, dict): raise ModelCompatibilityError("模型 SSE JSON 根对象无效", False, "protocol")
                choices = chunk.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict): raise ModelCompatibilityError("模型 SSE choices 无效", False, "protocol")
                delta = choices[0].get("delta")
                if not isinstance(delta, dict): raise ModelCompatibilityError("模型 SSE delta 无效", False, "protocol")
                if isinstance(delta.get("reasoning_content"), str): reasoning.append(delta["reasoning_content"])
                if isinstance(delta.get("content"), str):
                    content.append(delta["content"])
                calls = delta.get("tool_calls", [])
                if not isinstance(calls, list): raise ModelCompatibilityError("模型 SSE tool_calls 无效", False, "protocol")
                for item in calls:
                    if not isinstance(item, dict): raise ModelCompatibilityError("模型 SSE tool item 无效", False, "protocol")
                    try: index = int(item.get("index", 0))
                    except (TypeError, ValueError) as exc: raise ModelCompatibilityError("模型 SSE tool index 无效", False, "protocol") from exc
                    if index < 0 or index > 64: raise ModelCompatibilityError("模型 SSE tool index 超出范围", False, "protocol")
                    target = tool_calls.setdefault(index, {"function": {"name": "", "arguments": ""}})
                    function = item.get("function") or {}
                    if not isinstance(function, dict): raise ModelCompatibilityError("模型 SSE tool function 无效", False, "protocol")
                    target["function"]["name"] += str(function.get("name") or "")
                    target["function"]["arguments"] += str(function.get("arguments") or "")
    except ModelCompatibilityError:
        raise
    except httpx.HTTPStatusError as exc:
        raise ModelCompatibilityError(f"模型兼容性请求失败（HTTP {exc.response.status_code}）", exc.response.status_code >= 500 or exc.response.status_code == 429, "http") from exc
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        raise ModelCompatibilityError("无法在限定时间内连接模型服务", True, "network") from exc
    if not saw_done:
        raise ModelCompatibilityError("模型流式响应未正常完成", True, "incomplete_sse")
    return {"content": "".join(content), "reasoning_content": "".join(reasoning), "tool_calls": [tool_calls[key] for key in sorted(tool_calls)]}


async def check_model_compatibility(
    connection: Any,
    capabilities: dict,
    *,
    timeout_seconds: float | None = None,
    context_chars: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Probe only asserted capabilities; successful HTTP alone is never enough."""
    if not getattr(connection, "api_key", ""):
        raise ModelCompatibilityError("服务器未配置模型 API Key，不能发布模型", False, "missing_key")
    if capabilities.get("streaming") is not True or capabilities.get("tool_calls") is not True:
        raise ModelCompatibilityError("当前 Agent 要求 Streaming 和 Tool calls 能力均为 true", False, "required_capability")
    timeout_seconds, context_chars = compatibility_limits(timeout_seconds, context_chars)
    endpoint = f"{str(connection.base_url).rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {connection.api_key}", "Content-Type": "application/json"}
    started = time.perf_counter()
    owned_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds), follow_redirects=False)
    checks: list[dict] = []
    probe_options = provider_request_options(connection.provider, bool(capabilities.get("thinking")))
    try:
        basic = await _stream_probe(client, endpoint, headers, {
            "model": connection.model, "messages": [{"role": "user", "content": "Reply exactly: ok"}], "max_tokens": 8, **probe_options,
        })
        if not basic["content"].strip():
            raise ModelCompatibilityError("模型未返回有效的流式增量内容", False, "streaming")
        checks.append({"name": "connectivity_streaming", "status": "passed"})
        tool_name = "compatibility_probe"
        tool_payload = {
            "model": connection.model, "messages": [{"role": "user", "content": "Call the required function."}], "max_tokens": 16,
            "tools": [{"type": "function", "function": {"name": tool_name, "description": "Compatibility probe", "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}}}],
            **probe_options,
        }
        deepseek_thinking_tool_probe = capabilities.get("thinking") and connection.provider == "deepseek"
        if deepseek_thinking_tool_probe:
            tool_payload.update(provider_request_options(connection.provider, True))
        else:
            tool_payload["tool_choice"] = {"type": "function", "function": {"name": tool_name}}
        tool = await _stream_probe(client, endpoint, headers, tool_payload)
        if capabilities.get("thinking") and connection.provider == "deepseek" and not tool["reasoning_content"].strip():
            raise ModelCompatibilityError("Thinking 工具调用未返回 reasoning 内容", False, "thinking_tool")
        calls = tool["tool_calls"]
        if len(calls) != 1 or calls[0]["function"]["name"] != tool_name:
            raise ModelCompatibilityError("模型没有返回要求的函数调用", False, "tool_calls")
        try:
            if not isinstance(json.loads(calls[0]["function"]["arguments"]), dict):
                raise ValueError("not object")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelCompatibilityError("模型函数调用参数不是合法 JSON 对象", False, "tool_arguments") from exc
        checks.append({"name": "tool_calls", "status": "passed"})
        context = await _stream_probe(client, endpoint, headers, {
            "model": connection.model, "messages": [{"role": "user", "content": ("x " * ((context_chars // 2) + 1))[:context_chars]}], "max_tokens": 4, **probe_options,
        })
        if not context["content"].strip():
            raise ModelCompatibilityError("模型未通过最低上下文负载检查", False, "context")
        checks.append({"name": "context", "status": "passed"})
        if capabilities.get("thinking"):
            thinking = await _stream_probe(client, endpoint, headers, {"model": connection.model, "messages": [{"role": "user", "content": "Reply ok"}], "max_tokens": 8, **probe_options})
            if not thinking["content"].strip() or (connection.provider == "deepseek" and not thinking["reasoning_content"].strip()):
                raise ModelCompatibilityError("Thinking 探针未返回有效响应", False, "thinking")
            checks.append({"name": "thinking", "status": "passed"})
        if capabilities.get("native_multimodal"):
            image = await _stream_probe(client, endpoint, headers, {"model": connection.model, "messages": [{"role": "user", "content": [{"type": "text", "text": "Identify the 1px black image. Reply exactly BLACK."}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL1JwAAAABJRU5ErkJggg=="}}]}], "max_tokens": 8, **probe_options})
            if "BLACK" not in image["content"].upper():
                raise ModelCompatibilityError("多模态探针未返回有效响应", False, "multimodal")
            checks.append({"name": "native_multimodal", "status": "passed"})
    finally:
        if owned_client:
            await client.aclose()
    checks.append({"name": "limits", "status": "passed", "context_chars": context_chars})
    return {"status": "passed", "checked_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "checks": checks, "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
