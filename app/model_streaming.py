"""Provider streaming protocol parsing and model transport policies."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

ProgressCallback = Callable[[dict], Any]
NotifyCallback = Callable[[ProgressCallback | None, dict], Awaitable[None]]
DisclosureChecker = Callable[[str], bool]


async def stream_completion(
    client: httpx.AsyncClient,
    endpoint: str,
    headers: dict,
    request_payload: dict,
    progress: ProgressCallback | None,
    stream_state: dict[str, Any] | None = None,
    *,
    notify: NotifyCallback,
    disclosure_checker: DisclosureChecker,
) -> tuple[dict, dict, str | None]:
    """Parse an OpenAI-compatible SSE stream without exposing reasoning content."""
    stream_state = stream_state if stream_state is not None else {}
    payload = {
        **request_payload,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    pending_answer_parts: list[str] = []
    pending_answer_length = 0
    answer_started = False
    has_tool_calls = False
    tool_parts: dict[int, dict] = {}
    usage: dict = {}
    finish_reason: str | None = None
    response_id: str | None = None
    done_received = False
    stream_started = time.perf_counter()
    last_content_at: float | None = None

    def record_content_delta(content: str) -> None:
        nonlocal last_content_at
        now = time.perf_counter()
        if last_content_at is None:
            stream_state["first_content_ms"] = round((now - stream_started) * 1000, 1)
        else:
            gap_ms = round((now - last_content_at) * 1000, 1)
            stream_state["max_content_gap_ms"] = max(
                float(stream_state.get("max_content_gap_ms", 0)), gap_ms
            )
        last_content_at = now
        stream_state["content_delta_count"] = (
            int(stream_state.get("content_delta_count", 0)) + 1
        )
        stream_state["content_chars"] = int(stream_state.get("content_chars", 0)) + len(
            content
        )

    def suppress_pending_content() -> bool:
        if not stream_state.get("suppress_embedded_tool_json"):
            return False
        pending = "".join(pending_answer_parts).lstrip().lower()
        return pending.startswith("```json") or pending.startswith("{")

    async with client.stream(
        "POST", endpoint, headers=headers, json=payload
    ) as response:
        response.raise_for_status()
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                done_received = True
                break
            chunk = json.loads(data)
            response_id = response_id or chunk.get("id")
            if chunk.get("usage"):
                usage = chunk["usage"]
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or {}
            reasoning_content = delta.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content:
                reasoning_parts.append(reasoning_content)
                stream_state["reasoning_length"] = int(
                    stream_state.get("reasoning_length", 0)
                ) + len(reasoning_content)
            content = delta.get("content")
            if content:
                record_content_delta(content)
                content_parts.append(content)
                if answer_started:
                    stream_state["answer_emitted"] = True
                    await notify(progress, {"event": "answer_delta", "delta": content})
                elif not has_tool_calls:
                    pending_answer_parts.append(content)
                    pending_answer_length += len(content)
                    if pending_answer_length >= 64:
                        if suppress_pending_content():
                            continue
                        required_disclosure = str(
                            stream_state.get("required_disclosure") or ""
                        )
                        pending_text = "".join(pending_answer_parts)
                        if required_disclosure and not disclosure_checker(pending_text):
                            await notify(
                                progress,
                                {
                                    "event": "answer_delta",
                                    "delta": f"> {required_disclosure}\n\n",
                                },
                            )
                            stream_state["disclosure_emitted"] = True
                        answer_started = True
                        stream_state["answer_emitted"] = True
                        for part in pending_answer_parts:
                            await notify(
                                progress, {"event": "answer_delta", "delta": part}
                            )
                        pending_answer_parts.clear()
            for tool_delta in delta.get("tool_calls") or []:
                has_tool_calls = True
                pending_answer_parts.clear()
                index = int(tool_delta.get("index", 0))
                item = tool_parts.setdefault(
                    index,
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if tool_delta.get("id"):
                    item["id"] = tool_delta["id"]
                function_delta = tool_delta.get("function") or {}
                if function_delta.get("name"):
                    item["function"]["name"] += function_delta["name"]
                if function_delta.get("arguments"):
                    item["function"]["arguments"] += function_delta["arguments"]
    # A transport EOF is not a successful OpenAI-compatible completion.  In
    # particular, accepting a partial answer here would make callers persist a
    # response that the provider never completed.
    if not done_received:
        raise ValueError("model stream ended before final [DONE]")
    assistant = {"role": "assistant", "content": "".join(content_parts)}
    if tool_parts:
        assistant["tool_calls"] = [tool_parts[index] for index in sorted(tool_parts)]
        if reasoning_parts:
            assistant["reasoning_content"] = "".join(reasoning_parts)
    elif not answer_started and not suppress_pending_content():
        if pending_answer_parts:
            required_disclosure = str(stream_state.get("required_disclosure") or "")
            pending_text = "".join(pending_answer_parts)
            if required_disclosure and not disclosure_checker(pending_text):
                await notify(
                    progress,
                    {
                        "event": "answer_delta",
                        "delta": f"> {required_disclosure}\n\n",
                    },
                )
                stream_state["disclosure_emitted"] = True
            stream_state["answer_emitted"] = True
        for part in pending_answer_parts:
            await notify(progress, {"event": "answer_delta", "delta": part})
    stream_state["finish_reason"] = finish_reason
    stream_state["stream_duration_ms"] = round(
        (time.perf_counter() - stream_started) * 1000, 1
    )
    return assistant, usage, response_id


def audit_assistant(assistant: dict | None) -> dict:
    """Reasoning traces are provider continuation data, never observability data."""
    if not assistant:
        return {}
    return {
        key: value for key, value in assistant.items() if key != "reasoning_content"
    }


def retryable_model_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500
    return isinstance(exc, httpx.RequestError)


def model_error_category(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return "rate_limit" if exc.response.status_code == 429 else "upstream_5xx"
    return "timeout" if isinstance(exc, httpx.TimeoutException) else "network"


def model_retry_delay(base_seconds: float, retry_number: int, exc: Exception) -> float:
    if isinstance(exc, httpx.HTTPStatusError):
        retry_after = exc.response.headers.get("retry-after")
        try:
            if retry_after is not None:
                return max(0.05, min(float(retry_after), 8.0))
        except ValueError:
            pass
    base = min(base_seconds * (2 ** max(0, retry_number - 1)), 8.0)
    return base + random.uniform(0, base * 0.2)
