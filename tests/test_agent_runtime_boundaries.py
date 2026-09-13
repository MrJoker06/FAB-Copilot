from __future__ import annotations

import inspect
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent_runtime import service as agent
from app.agent_runtime.contracts import AgentRunLifecycle, AgentRunRequest
from app.agent_runtime.coordinator import CoordinatorDependencies, coordinate_agent_run
from app.agent_runtime.coordinator_availability import handle_model_availability as legacy_availability
from app.agent_runtime.coordinator_loop import execute_agent_loop as legacy_loop
from app.agent_runtime.coordinator_model import prepare_model_stage as legacy_model
from app.agent_runtime.coordinator_prepare import prepare_immediate as legacy_prepare
from app.agent_runtime.coordinator_ready import execute_ready_synthesis
from app.agent_runtime.coordinator_state import CoordinatorRunState
from app.agent_runtime.dependencies import (
    AvailabilityDependencies,
    LoopDependencies,
    ModelDependencies,
    PreparationDependencies,
    ReadyDependencies,
)
from app.agent_runtime.stages import (
    execute_agent_loop,
    handle_model_availability,
    prepare_immediate,
    prepare_model_stage,
)
from app.agent_runtime.telemetry import notify


class AgentRuntimeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_compatibility_exports_preserve_async_reflection_for_patching(self):
        async_names = (
            "_notify", "_stream_answer", "_execute_ready_plan",
            "_request_ready_synthesis", "_prefetch_general_knowledge",
            "_stream_completion", "_resolve_conversation_turn",
        )
        for name in async_names:
            self.assertTrue(inspect.iscoroutinefunction(getattr(agent, name)), name)

        with patch("app.agent_runtime.service._notify") as async_mock:
            self.assertIsInstance(async_mock, AsyncMock)
        with patch("app.agent_runtime.service._emit_answer_synthesis") as sync_mock:
            self.assertIsInstance(sync_mock, MagicMock)
            self.assertNotIsInstance(sync_mock, AsyncMock)
        self.assertFalse(inspect.iscoroutinefunction(agent._emit_answer_synthesis))

    def test_coordinator_state_default_containers_are_run_local(self):
        first = CoordinatorRunState("问题一", None, "run-1", None, False)
        second = CoordinatorRunState("问题二", None, "run-2", None, False)

        first.trace.append({"tool": "one"})
        first.sources["one"] = {"reference_id": "one"}
        first.total_usage["total_tokens"] = 1
        first.knowledge_fallback["used"] = True

        self.assertEqual(second.trace, [])
        self.assertEqual(second.sources, {})
        self.assertEqual(second.total_usage, {})
        self.assertEqual(second.knowledge_fallback, {})

    def test_coordinator_state_views_are_live_and_run_local(self):
        first = CoordinatorRunState("问题一", None, "run-1", None, False)
        second = CoordinatorRunState("问题二", None, "run-2", None, False)

        first.preparation_state.analysis_question = "归一化问题"
        first.model_state.messages = [{"role": "system", "content": "提示"}]
        first.result_state.trace = [{"tool": "one"}]

        self.assertEqual(first.analysis_question, "归一化问题")
        self.assertEqual(first.messages, [{"role": "system", "content": "提示"}])
        self.assertEqual(first.trace, [{"tool": "one"}])
        self.assertEqual(second.analysis_question, "")
        self.assertEqual(second.messages, [])
        self.assertEqual(second.trace, [])

    def test_stage_shims_and_dependency_groups_preserve_legacy_access(self):
        self.assertIs(legacy_prepare, prepare_immediate)
        self.assertIs(legacy_availability, handle_model_availability)
        self.assertIs(legacy_model, prepare_model_stage)
        self.assertIs(legacy_loop, execute_agent_loop)
        self.assertIn("stages.ready", execute_ready_synthesis.__module__)
        self.assertNotIn("async def", inspect.getsource(sys.modules["app.agent_runtime.coordinator_prepare"]))

        deps = agent._coordinator_dependencies()
        self.assertIsInstance(deps, CoordinatorDependencies)
        self.assertIsInstance(deps.preparation, PreparationDependencies)
        self.assertIsInstance(deps.availability, AvailabilityDependencies)
        self.assertIsInstance(deps.model, ModelDependencies)
        self.assertIsInstance(deps.ready, ReadyDependencies)
        self.assertIsInstance(deps.loop, LoopDependencies)
        self.assertIs(deps.prepare_agent_run, deps.preparation.prepare_agent_run)
        self.assertIs(deps.stream_answer, deps.preparation.stream_answer)

    async def test_ready_stage_skips_non_ready_plan(self):
        state = CoordinatorRunState("问题", None, "run-1", None, False)
        state.execution_plan = SimpleNamespace(status="needs_model")

        self.assertIsNone(await execute_ready_synthesis(state, deps=object()))

    def test_request_preserves_legacy_input_identity(self):
        history = [{"role": "user", "content": "原始对象"}]
        request = AgentRunRequest("问题", history, "run-1", thinking=True)

        self.assertEqual(request.question, "问题")
        self.assertIs(request.history, history)
        self.assertEqual((request.run_id, request.thinking), ("run-1", True))

    async def test_run_impl_preserves_history_and_constructs_live_dependencies(self):
        history = [{"role": "user"}]
        result = {"answer": "完成"}
        coordinator = AsyncMock(return_value=result)

        with patch("app.agent_runtime.service.coordinate_agent_run", new=coordinator):
            actual = await agent._run_agent_impl("问题", history, "run-1", thinking=True)

        self.assertIs(actual, result)
        request = coordinator.await_args.args[0]
        self.assertIsInstance(request, AgentRunRequest)
        self.assertIs(request.history, history)
        self.assertEqual((request.question, request.run_id, request.thinking), ("问题", "run-1", True))
        deps = coordinator.await_args.kwargs["deps"]
        self.assertIsInstance(deps, CoordinatorDependencies)
        self.assertIs(deps.prepare_agent_run, agent.prepare_agent_run)

    async def test_coordinator_propagates_dependency_exception(self):
        request = AgentRunRequest("问题", None, "run-1")
        preparation = AsyncMock(side_effect=RuntimeError("dependency failure"))

        with patch("app.agent_runtime.service.prepare_agent_run", new=preparation):
            deps = agent._coordinator_dependencies()
            with self.assertRaisesRegex(RuntimeError, "dependency failure"):
                await coordinate_agent_run(request, None, deps=deps)

        preparation.assert_awaited_once()

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
        with patch("app.agent_runtime.service._notify", new=capture_notify), patch("app.agent_runtime.service.asyncio.sleep", new=sleep):
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

        with patch("app.agent_runtime.service.emit", new=capture):
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
        with patch("app.agent_runtime.service._run_agent_impl", new=implementation), patch("app.agent_runtime.service.emit"):
            actual = await agent.run_agent("问题", history=[])

        self.assertIs(actual, result)
        self.assertEqual(implementation.await_args.args[:3], ("问题", [], actual["run_id"]))
        self.assertIsNotNone(implementation.await_args.args[3])
        self.assertFalse(implementation.await_args.args[4])


if __name__ == "__main__":
    unittest.main()
