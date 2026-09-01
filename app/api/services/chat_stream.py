from __future__ import annotations

import asyncio
import json
import traceback

import httpx
from fastapi.responses import StreamingResponse


class ChatStreamService:
    def __init__(self, deps):
        self._deps = deps

    @staticmethod
    def stream_line(event_type: str, **payload) -> bytes:
        return (
            json.dumps({"type": event_type, **payload}, ensure_ascii=False, default=str)
            + "\n"
        ).encode("utf-8")

    def chat_stream(self, request) -> StreamingResponse:
        runtime = self._deps()
        principal, selected_model = runtime["_validate_chat_model_capabilities"](
            request
        )
        session_id, history, cached, user_message = runtime["_prepare_chat"](request)
        recorder = runtime["RunExecutionRecorder"](
            session_id,
            user_message["message_id"] if user_message else None,
            request.message,
            selected_model,
        )

        async def event_stream():
            yield runtime["_stream_line"]("session", session_id=session_id)
            if cached:
                cached["session_id"] = session_id
                cached["request_id"] = runtime["current_request_id"]()
                yield runtime["_stream_line"]("result", result=cached)
                return
            runtime["begin_agent_run"](
                principal, session_id, request.message, selected_model
            )
            activity_finished = False
            queue: asyncio.Queue[tuple[dict, float]] = asyncio.Queue()
            stream_started = asyncio.get_running_loop().time()
            delivery = {
                "answer_events": 0,
                "answer_chars": 0,
                "first_answer_ms": None,
                "max_enqueue_gap_ms": 0.0,
                "max_queue_wait_ms": 0.0,
                "max_sse_gap_ms": 0.0,
            }
            last_answer_enqueued: float | None = None
            first_answer_yielded: float | None = None
            last_answer_yielded: float | None = None

            async def progress(event: dict) -> None:
                nonlocal last_answer_enqueued
                await recorder.observe(event)
                enqueued_at = asyncio.get_running_loop().time()
                if event.get("event") == "answer_delta":
                    delivery["answer_events"] += 1
                    delivery["answer_chars"] += len(str(event.get("delta") or ""))
                    if last_answer_enqueued is None:
                        delivery["first_answer_ms"] = round(
                            (enqueued_at - stream_started) * 1000, 1
                        )
                    else:
                        delivery["max_enqueue_gap_ms"] = max(
                            delivery["max_enqueue_gap_ms"],
                            round((enqueued_at - last_answer_enqueued) * 1000, 1),
                        )
                    last_answer_enqueued = enqueued_at
                await queue.put((event, enqueued_at))
                await asyncio.sleep(0)

            task = asyncio.create_task(
                runtime["run_agent"](
                    request.message,
                    history,
                    progress,
                    thinking=request.thinking,
                    session_id=session_id,
                    user_message_id=user_message["message_id"]
                    if user_message
                    else None,
                )
            )
            try:
                while not task.done() or not queue.empty():
                    try:
                        event, enqueued_at = await asyncio.wait_for(
                            queue.get(), timeout=0.25
                        )
                    except TimeoutError:
                        continue
                    now = asyncio.get_running_loop().time()
                    delivery["max_queue_wait_ms"] = max(
                        delivery["max_queue_wait_ms"],
                        round((now - enqueued_at) * 1000, 1),
                    )
                    if event.get("event") == "answer_delta":
                        if first_answer_yielded is None:
                            first_answer_yielded = now
                        if last_answer_yielded is not None:
                            delivery["max_sse_gap_ms"] = max(
                                delivery["max_sse_gap_ms"],
                                round((now - last_answer_yielded) * 1000, 1),
                            )
                        last_answer_yielded = now
                    yield runtime["_stream_line"]("progress", **event)
                result = await task
                delivery["duration_ms"] = round(
                    (asyncio.get_running_loop().time() - stream_started) * 1000, 1
                )
                delivery["answer_stream_duration_ms"] = (
                    round((last_answer_yielded - first_answer_yielded) * 1000, 1)
                    if first_answer_yielded is not None
                    and last_answer_yielded is not None
                    else None
                )
                trace_semantics = result.setdefault(
                    "trace_semantics", {"schema_version": "1.0"}
                )
                if isinstance(trace_semantics, dict):
                    trace_semantics["stream_duration_ms"] = delivery[
                        "answer_stream_duration_ms"
                    ]
                recorder.complete(result)
                result["session_id"] = session_id
                result["request_id"] = runtime["current_request_id"]()
                result["client_message_id"] = request.client_message_id
                message = runtime["append_message"](
                    session_id, "assistant", result["answer"], result
                )
                runtime["record_agent_result"](
                    session_id,
                    message["message_id"],
                    result,
                    user_message_id=user_message["message_id"]
                    if user_message
                    else None,
                    question=request.message,
                )
                runtime["emit"](
                    "agent_run_persisted",
                    str(result.get("run_id") or session_id),
                    session_id=session_id,
                    user_message_id=user_message["message_id"]
                    if user_message
                    else None,
                    assistant_message_id=message["message_id"],
                )
                runtime["finish_agent_run"](
                    principal,
                    "success",
                    str(result.get("run_id") or ""),
                    str(result.get("model") or selected_model),
                )
                activity_finished = True
                runtime["emit"](
                    "stream_delivery_summary",
                    str(result.get("run_id") or session_id),
                    **delivery,
                )
                yield runtime["_stream_line"](
                    "progress",
                    event="stream_delivery_summary",
                    run_id=result.get("run_id"),
                    **delivery,
                )
                yield runtime["_stream_line"]("result", result=result)
            except asyncio.CancelledError:
                task.cancel()
                recorder.fail("客户端已断开连接", interrupted=True)
                runtime["finish_agent_run"](
                    principal, "error", model=selected_model, error="客户端已断开连接"
                )
                activity_finished = True
                raise
            except httpx.HTTPStatusError as exc:
                recorder.fail(str(exc))
                runtime["finish_agent_run"](
                    principal, "error", model=selected_model, error=str(exc)
                )
                activity_finished = True
                detail, retryable = runtime["_model_status_error"](exc)
                problem = runtime["error_payload"](
                    "MODEL_UPSTREAM_ERROR", detail, retryable
                )
                runtime["emit"](
                    "api_stream_error",
                    runtime["current_request_id"]() or session_id,
                    status="error",
                    error_type="MODEL_UPSTREAM_ERROR",
                    session_id=session_id,
                    retryable=retryable,
                )
                yield runtime["_stream_line"]("error", detail=detail, error=problem)
            except httpx.RequestError as exc:
                recorder.fail(str(exc))
                runtime["finish_agent_run"](
                    principal, "error", model=selected_model, error=str(exc)
                )
                activity_finished = True
                detail = f"无法连接模型 API: {exc}"
                runtime["emit"](
                    "api_stream_error",
                    runtime["current_request_id"]() or session_id,
                    status="error",
                    error_type="MODEL_NETWORK_ERROR",
                    session_id=session_id,
                    retryable=True,
                )
                yield runtime["_stream_line"](
                    "error",
                    detail=detail,
                    error=runtime["error_payload"]("MODEL_NETWORK_ERROR", detail, True),
                )
            except Exception as exc:
                recorder.fail(str(exc))
                runtime["finish_agent_run"](
                    principal, "error", model=selected_model, error=str(exc)
                )
                activity_finished = True
                detail = f"分析失败: {exc}"
                runtime["emit"](
                    "api_stream_error",
                    runtime["current_request_id"]() or session_id,
                    status="error",
                    error_type=type(exc).__name__,
                    session_id=session_id,
                    retryable=False,
                    full_content={
                        "error_message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
                yield runtime["_stream_line"](
                    "error",
                    detail=detail,
                    error=runtime["error_payload"]("ANALYSIS_ERROR", detail, False),
                )
            finally:
                if not task.done():
                    task.cancel()
                if not activity_finished:
                    runtime["finish_agent_run"](
                        principal,
                        "error",
                        model=selected_model,
                        error="Agent 运行未正常完成",
                    )

        return StreamingResponse(
            event_stream(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
