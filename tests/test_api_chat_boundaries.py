from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
import httpx

import app.main as main


class ApiChatBoundaryTests(unittest.TestCase):
    @staticmethod
    async def _collect(response) -> list[dict]:
        return [json.loads(item) async for item in response.body_iterator]

    def test_main_exports_extracted_chat_implementations(self):
        self.assertEqual(main.chat.__module__, "app.api.routers.chat")
        self.assertEqual(main.chat_stream.__module__, "app.api.routers.chat")
        self.assertEqual(main._prepare_chat.__self__, main._chat_service)
        self.assertIs(main._stream_line, main._chat_stream_service.stream_line)

    def test_ndjson_line_is_utf8_and_one_line(self):
        class Value:
            def __str__(self):
                return "可编码对象"

        line = main._stream_line("progress", message="中文", value=Value())
        self.assertTrue(line.endswith(b"\n"))
        self.assertFalse(line.endswith(b"\n\n"))
        self.assertNotIn(b"\\u4e2d", line)
        self.assertEqual(
            json.loads(line.decode()),
            {"type": "progress", "message": "中文", "value": "可编码对象"},
        )

    def test_capability_check_precedes_session_writes(self):
        request = main.ChatRequest(message="xx", thinking=True)
        with (
            patch.object(main, "current_principal", return_value=Mock()),
            patch.object(
                main,
                "public_user_model_config",
                return_value={"model": "m", "capabilities": {"thinking": False}},
            ),
            patch.object(main, "create_session") as create_session,
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(main._chat_service.chat(request))
            self.assertEqual(raised.exception.status_code, 400)
            create_session.assert_not_called()

    def test_chat_service_uses_live_main_run_agent_patch(self):
        request = main.ChatRequest(message="xx")
        events = []

        async def fake_agent(*_args, **_kwargs):
            events.append("run")
            return {"answer": "ok", "run_id": "run-1"}

        with (
            patch.object(
                main, "_validate_chat_model_capabilities", return_value=("p", "m")
            ),
            patch.object(
                main, "_prepare_chat", return_value=("s", [], None, {"message_id": "u"})
            ),
            patch.object(main, "RunExecutionRecorder", return_value=Mock()),
            patch.object(main, "begin_agent_run"),
            patch.object(main, "run_agent", new=fake_agent),
            patch.object(main, "append_message", return_value={"message_id": "a"}),
            patch.object(main, "record_agent_result"),
            patch.object(main, "emit"),
            patch.object(main, "finish_agent_run"),
        ):
            result = asyncio.run(main._chat_service.chat(request))
        self.assertEqual(result["answer"], "ok")
        self.assertEqual(events, ["run"])

    def test_cached_chat_does_not_start_agent_run(self):
        request = main.ChatRequest(message="xx")
        cached = {"answer": "cached", "cached": True}
        with (
            patch.object(
                main, "_validate_chat_model_capabilities", return_value=("p", "m")
            ),
            patch.object(main, "_prepare_chat", return_value=("s", [], cached, None)),
            patch.object(main, "begin_agent_run") as begin,
            patch.object(main, "run_agent", new=AsyncMock()) as run,
        ):
            result = asyncio.run(main._chat_service.chat(request))
        self.assertEqual(result["session_id"], "s")
        begin.assert_not_called()
        run.assert_not_awaited()

    def test_prepare_chat_reads_before_append_once_through_live_main_patch(self):
        request = main.ChatRequest(message="消息内容")
        events = []

        def session_history(session_id):
            events.append(("read", session_id))
            return [{"role": "assistant", "content": "已有回答"}]

        def append_message(*args, **kwargs):
            events.append(("append", args[1], args[2]))
            return {"message_id": "u-1"}

        with (
            patch.object(main, "create_session", return_value={"session_id": "s-1"}),
            patch.object(main, "client_message_content", return_value=None),
            patch.object(main, "cached_agent_result", return_value=None),
            patch.object(main, "session_history", new=session_history),
            patch.object(main, "append_message", new=append_message),
        ):
            session_id, history, cached, message = main._prepare_chat(request)
        self.assertEqual((session_id, history, cached, message), (
            "s-1", [{"role": "assistant", "content": "已有回答"}], None, {"message_id": "u-1"},
        ))
        self.assertEqual(events, [("read", "s-1"), ("append", "user", "消息内容")])

    def test_prepare_chat_cached_result_performs_no_history_read(self):
        request = main.ChatRequest(message="消息内容", client_message_id="message-1")
        cached = {"answer": "cached"}
        with (
            patch.object(main, "create_session", return_value={"session_id": "s-1"}),
            patch.object(main, "client_message_content", return_value=None),
            patch.object(main, "cached_agent_result", return_value=cached),
            patch.object(main, "session_history", side_effect=AssertionError) as history,
            patch.object(main, "append_message", side_effect=AssertionError),
        ):
            self.assertEqual(main._prepare_chat(request), ("s-1", [], cached, None))
        history.assert_not_called()

    def test_prepare_chat_removes_duplicate_persisted_user_message(self):
        request = main.ChatRequest(message="消息内容")
        with (
            patch.object(main, "create_session", return_value={"session_id": "s-1"}),
            patch.object(main, "client_message_content", return_value=None),
            patch.object(main, "cached_agent_result", return_value=None),
            patch.object(
                main, "session_history",
                return_value=[
                    {"role": "assistant", "content": "回答"},
                    {"role": "user", "content": "消息内容"},
                ],
            ),
            patch.object(main, "append_message", return_value={"message_id": "u-1", "duplicate": True}),
        ):
            _, history, _, _ = main._prepare_chat(request)
        self.assertEqual(history, [{"role": "assistant", "content": "回答"}])

    def test_chat_uses_persisted_history_before_explicit_request_history(self):
        request = main.ChatRequest(
            message="消息内容",
            history=[main.ChatMessage(role="user", content="显式历史")],
        )
        captured = []

        async def fake_agent(*args, **_kwargs):
            captured.append(args[1])
            return {"answer": "ok", "run_id": "run-1"}

        with (
            patch.object(main, "_validate_chat_model_capabilities", return_value=("p", "m")),
            patch.object(
                main, "_prepare_chat",
                return_value=("s", [{"role": "assistant", "content": "持久历史"}], None, {"message_id": "u"}),
            ),
            patch.object(main, "RunExecutionRecorder", return_value=Mock()),
            patch.object(main, "begin_agent_run"),
            patch.object(main, "run_agent", new=fake_agent),
            patch.object(main, "append_message", return_value={"message_id": "a"}),
            patch.object(main, "record_agent_result"),
            patch.object(main, "emit"),
            patch.object(main, "finish_agent_run"),
        ):
            asyncio.run(main._chat_service.chat(request))
        self.assertEqual(captured, [[{"role": "assistant", "content": "持久历史"}]])

    def test_chat_falls_back_to_explicit_history_when_persisted_history_is_empty(self):
        request = main.ChatRequest(
            message="消息内容",
            history=[main.ChatMessage(role="user", content="显式历史")],
        )
        captured = []

        async def fake_agent(*args, **_kwargs):
            captured.append(args[1])
            return {"answer": "ok", "run_id": "run-1"}

        with (
            patch.object(main, "_validate_chat_model_capabilities", return_value=("p", "m")),
            patch.object(main, "_prepare_chat", return_value=("s", [], None, {"message_id": "u"})),
            patch.object(main, "RunExecutionRecorder", return_value=Mock()),
            patch.object(main, "begin_agent_run"),
            patch.object(main, "run_agent", new=fake_agent),
            patch.object(main, "append_message", return_value={"message_id": "a"}),
            patch.object(main, "record_agent_result"),
            patch.object(main, "emit"),
            patch.object(main, "finish_agent_run"),
        ):
            asyncio.run(main._chat_service.chat(request))
        self.assertEqual(captured, [[{"role": "user", "content": "显式历史"}]])

    def test_cached_stream_returns_session_then_result_without_running_agent(self):
        request = main.ChatRequest(message="缓存请求", client_message_id="message-001")
        cached = {"answer": "cached", "cached": True}
        recorder = Mock()
        with (
            patch.object(
                main, "_validate_chat_model_capabilities", return_value=("p", "m")
            ),
            patch.object(main, "_prepare_chat", return_value=("s-1", [], cached, None)),
            patch.object(main, "RunExecutionRecorder", return_value=recorder),
            patch.object(main, "current_request_id", return_value="req-1"),
            patch.object(main, "begin_agent_run") as begin,
            patch.object(main, "run_agent", new=AsyncMock()) as run,
        ):
            response = main._chat_stream_service.chat_stream(request)
            events = asyncio.run(self._collect(response))
        self.assertEqual([event["type"] for event in events], ["session", "result"])
        self.assertEqual(events[0]["session_id"], "s-1")
        self.assertEqual(events[1]["result"]["session_id"], "s-1")
        self.assertEqual(events[1]["result"]["request_id"], "req-1")
        self.assertTrue(events[1]["result"]["cached"])
        begin.assert_not_called()
        run.assert_not_awaited()
        recorder.complete.assert_not_called()

    def test_stream_request_and_analysis_errors_are_structured_and_audited(self):
        request = main.ChatRequest(message="故障请求")
        cases = (
            (
                httpx.RequestError("offline"),
                "MODEL_NETWORK_ERROR",
                True,
                "MODEL_NETWORK_ERROR",
            ),
            (RuntimeError("broken"), "ANALYSIS_ERROR", False, "RuntimeError"),
        )
        for failure, error_code, retryable, emitted_type in cases:
            with self.subTest(error_code=error_code):
                recorder = Mock()
                emitted = []

                async def failing_agent(*_args, **_kwargs):
                    raise failure

                def emit(event_type, run_id, **fields):
                    emitted.append((event_type, run_id, fields))

                with (
                    patch.object(
                        main,
                        "_validate_chat_model_capabilities",
                        return_value=("principal", "model-1"),
                    ),
                    patch.object(
                        main,
                        "_prepare_chat",
                        return_value=("s-2", [], None, {"message_id": "u-2"}),
                    ),
                    patch.object(main, "RunExecutionRecorder", return_value=recorder),
                    patch.object(main, "run_agent", new=failing_agent),
                    patch.object(main, "begin_agent_run"),
                    patch.object(main, "finish_agent_run") as finish,
                    patch.object(main, "current_request_id", return_value="req-2"),
                    patch.object(main, "emit", new=emit),
                ):
                    events = asyncio.run(
                        self._collect(main._chat_stream_service.chat_stream(request))
                    )
                self.assertEqual(events[-1]["type"], "error")
                self.assertEqual(events[-1]["error"]["error_code"], error_code)
                recorder.fail.assert_called_once_with(str(failure))
                finish.assert_called_once_with(
                    "principal", "error", model="model-1", error=str(failure)
                )
                stream_error = next(
                    event for event in emitted if event[0] == "api_stream_error"
                )
                self.assertEqual(stream_error[1], "req-2")
                self.assertEqual(stream_error[2]["error_type"], emitted_type)
                self.assertEqual(stream_error[2]["retryable"], retryable)

    def test_stream_cancellation_marks_recorder_and_cancels_agent_task(self):
        request = main.ChatRequest(message="取消请求")

        async def run():
            started = asyncio.Event()
            cancelled = asyncio.Event()
            recorder = Mock()
            blocker = asyncio.Event()

            async def blocked_agent(*_args, **_kwargs):
                started.set()
                try:
                    await blocker.wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

            with (
                patch.object(
                    main,
                    "_validate_chat_model_capabilities",
                    return_value=("principal", "model-1"),
                ),
                patch.object(
                    main,
                    "_prepare_chat",
                    return_value=("s-3", [], None, {"message_id": "u-3"}),
                ),
                patch.object(main, "RunExecutionRecorder", return_value=recorder),
                patch.object(main, "run_agent", new=blocked_agent),
                patch.object(main, "begin_agent_run"),
                patch.object(main, "finish_agent_run") as finish,
            ):
                response = main._chat_stream_service.chat_stream(request)
                iterator = response.body_iterator
                self.assertEqual(json.loads(await anext(iterator))["type"], "session")
                pending = asyncio.create_task(anext(iterator))
                await started.wait()
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
                await cancelled.wait()
            recorder.fail.assert_called_once_with("客户端已断开连接", interrupted=True)
            finish.assert_called_once_with(
                "principal", "error", model="model-1", error="客户端已断开连接"
            )

        asyncio.run(run())

    def test_model_status_error_retryability_and_message_limit(self):
        request = httpx.Request("POST", "https://example.test/chat")
        for status_code, retryable in ((429, True), (503, True), (400, False)):
            with self.subTest(status_code=status_code):
                response = httpx.Response(
                    status_code,
                    json={"error": {"message": "x" * 400}},
                    request=request,
                )
                detail, actual_retryable = main._model_status_error(
                    httpx.HTTPStatusError("failed", request=request, response=response)
                )
                self.assertEqual(actual_retryable, retryable)
                self.assertEqual(detail, f"模型 API 返回 {status_code}: {'x' * 300}")


if __name__ == "__main__":
    unittest.main()
