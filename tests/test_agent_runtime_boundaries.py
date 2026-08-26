from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import agent
from app.agent_runtime.contracts import AgentRunLifecycle, AgentRunRequest
from app.agent_runtime.coordinator import coordinate_agent_run
from app.agent_runtime.telemetry import notify


class AgentRuntimeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_request_preserves_legacy_input_identity(self):
        history = [{"role": "user", "content": "原始对象"}]
        request = AgentRunRequest("问题", history, "run-1", thinking=True)

        self.assertEqual(request.question, "问题")
        self.assertIs(request.history, history)
        self.assertEqual((request.run_id, request.thinking), ("run-1", True))

    async def test_coordinator_forwards_exact_legacy_arguments_and_result(self):
        history = [{"role": "user"}]
        request = AgentRunRequest("问题", history, "run-1", thinking=True)
        progress = object()
        result = {"answer": "完成"}
        implementation = AsyncMock(return_value=result)

        actual = await coordinate_agent_run(
            request,
            progress,
            implementation=implementation,
        )

        self.assertIs(actual, result)
        implementation.assert_awaited_once_with("问题", history, "run-1", progress, True)

    async def test_coordinator_propagates_legacy_exception(self):
        request = AgentRunRequest("问题", None, "run-1")
        implementation = AsyncMock(side_effect=RuntimeError("legacy failure"))

        with self.assertRaisesRegex(RuntimeError, "legacy failure"):
            await coordinate_agent_run(request, None, implementation=implementation)

    def test_lifecycle_records_only_first_answer_delta(self):
        lifecycle = AgentRunLifecycle(10.0, "2026-08-26T00:00:00.000+00:00")

        lifecycle.observe_progress({"event": "stage"}, 12.0)
        lifecycle.observe_progress({"event": "answer_delta", "delta": "a"}, 10.1234)
        lifecycle.observe_progress({"event": "answer_delta", "delta": "b"}, 11.0)

        self.assertEqual(lifecycle.first_token_ms(), 123.4)
        self.assertEqual(lifecycle.duration_ms(10.98765), 987.7)

    async def test_notify_accepts_sync_and_async_callbacks(self):
        events: list[dict] = []

        def sync_callback(event: dict) -> None:
            events.append(event)

        async def async_callback(event: dict) -> None:
            events.append(event)

        await notify(None, {"event": "ignored"})
        await notify(sync_callback, {"event": "sync"})
        await notify(async_callback, {"event": "async"})

        self.assertEqual(events, [{"event": "sync"}, {"event": "async"}])

    async def test_stream_wrapper_uses_live_notify_and_sleep_with_legacy_chunks(self):
        events: list[dict] = []

        async def capture_notify(_progress, event: dict) -> None:
            events.append(event)

        sleep = AsyncMock()
        answer = "x" * 121
        with patch("app.agent._notify", new=capture_notify), patch("app.agent.asyncio.sleep", new=sleep):
            await agent._stream_answer(object(), answer)

        self.assertEqual([event["delta"] for event in events], ["x" * 120, "x"])
        self.assertEqual(sleep.await_args_list, [unittest.mock.call(0), unittest.mock.call(0)])

    def test_answer_synthesis_wrapper_uses_live_emit_callback(self):
        emitted: list[tuple[str, str, dict]] = []
        report = SimpleNamespace(
            plan_id="plan-1",
            status="valid",
            allowed_conclusion_strength="bounded",
            source_refs=("KB-1",),
            invalid_source_refs=(),
            moved_claims=1,
            wording_adjustments=("qualified",),
            to_dict=lambda: {"status": "valid"},
        )

        def capture(event_type: str, run_id: str, **fields) -> None:
            emitted.append((event_type, run_id, fields))

        with patch("app.agent.emit", new=capture):
            agent._emit_answer_synthesis("run-1", report)

        self.assertEqual(emitted, [("answer_synthesis_completed", "run-1", {
            "plan_id": "plan-1",
            "status": "valid",
            "allowed_conclusion_strength": "bounded",
            "source_count": 1,
            "invalid_source_count": 0,
            "moved_claims": 1,
            "wording_adjustment_count": 1,
            "full_content": {"answer_synthesis": {"status": "valid"}},
        })])

    async def test_run_agent_uses_live_legacy_implementation(self):
        result = {"answer": "完成", "tool_trace": [], "sources": []}
        implementation = AsyncMock(return_value=result)
        with patch("app.agent._run_agent_impl", new=implementation), patch("app.agent.emit"):
            actual = await agent.run_agent("问题", history=[])

        self.assertIs(actual, result)
        self.assertEqual(implementation.await_args.args[:3], ("问题", [], actual["run_id"]))
        self.assertIsNotNone(implementation.await_args.args[3])
        self.assertFalse(implementation.await_args.args[4])


if __name__ == "__main__":
    unittest.main()
