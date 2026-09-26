from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent_runtime import service as agent
from app.agent_runtime.preparation import ContextProtocolError
from app.agent_runtime.preparation.context import (
    ResolverDependencies,
    resolve_conversation_turn,
)
from app.memory_system.context.resolver import unresolved_context


class AgentPreparationBoundaryTests(unittest.TestCase):
    def test_context_protocol_facade_keeps_runtime_error_identity(self):
        self.assertIs(agent.ContextProtocolError, ContextProtocolError)
        with self.assertRaises(agent.ContextProtocolError) as captured:
            agent._context_json_arguments({"content": "not-json"})
        self.assertEqual(captured.exception.code, "invalid_json")

    def test_context_protocol_facade_normalizes_budget_exhaustion(self):
        original = agent.ContextProtocolError("empty_response", "empty")
        normalized = agent._normalized_context_protocol_error(original, "length")

        self.assertIsInstance(normalized, ContextProtocolError)
        self.assertEqual(normalized.code, "context_budget_exhausted")

    def test_run_impl_uses_live_context_and_planner_facades(self):
        resolved = unresolved_context("介绍一下你自己", "deterministic")
        resolve_turn = AsyncMock(return_value=(resolved, {}))
        real_create_plan = agent.create_execution_plan
        created: list[object] = []

        def capture_plan(question, route, selection):
            plan = real_create_plan(question, route, selection)
            created.append(plan)
            return plan

        with (
            patch("app.agent_runtime.service._resolve_conversation_turn", new=resolve_turn),
            patch("app.agent_runtime.service.create_execution_plan", new=capture_plan),
        ):
            result = asyncio.run(
                agent._run_agent_impl("介绍一下你自己", [], "prep-live-facade")
            )

        self.assertTrue(resolve_turn.await_count)
        self.assertEqual(len(created), 1)
        self.assertEqual(result["execution_plan"]["plan_id"], created[0].plan_id)

    def test_preparation_keeps_routing_planning_audit_and_progress_order(self):
        events: list[str] = []

        def capture_emit(event_type: str, _run_id: str, **_fields) -> None:
            if event_type in {
                "playbook_selected",
                "execution_plan_created",
                "routing_stage_completed",
            }:
                events.append(event_type)

        async def capture_progress(_progress, event: dict) -> None:
            if event.get("stage") in {"routing", "playbook", "plan"}:
                events.append(f"progress:{event['stage']}")

        with (
            patch("app.agent_runtime.service.emit", new=capture_emit),
            patch("app.agent_runtime.service._notify", new=capture_progress),
        ):
            asyncio.run(agent._run_agent_impl("介绍一下你自己", [], "prep-order"))

        self.assertEqual(
            events,
            [
                "progress:routing",
                "playbook_selected",
                "progress:playbook",
                "execution_plan_created",
                "routing_stage_completed",
                "progress:plan",
            ],
        )

    def test_context_stage_uses_run_start_tick_without_extra_initial_tick(self):
        context_durations: list[float] = []
        ticks = iter([10.0, 1_000.0, 1_000.25, 1_000.5, 1_000.75, 1_001.0])

        def capture_emit(event_type: str, _run_id: str, **fields) -> None:
            if event_type == "context_stage_completed":
                context_durations.append(fields["duration_ms"])

        with (
            patch("app.agent_runtime.service.time.perf_counter", side_effect=lambda: next(ticks)),
            patch("app.agent_runtime.service.emit", new=capture_emit),
        ):
            asyncio.run(agent._run_agent_impl("介绍一下你自己", [], "prep-timing"))

        self.assertEqual(context_durations, [990_000.0])

    def test_protocol_failure_recovers_circuit_with_one_run_id(self):
        emitted: list[tuple[str, tuple, dict]] = []

        @asynccontextmanager
        async def timeout(_seconds):
            yield

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        def capture_emit(event_type: str, *args, **fields) -> None:
            emitted.append((event_type, args, fields))

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(
                api_key="key",
                model="model-a",
                provider="openai",
                base_url="https://example.invalid",
            ),
            api_timeout_seconds=1,
            model_context_timeout_seconds=10,
            model_retry_base_seconds=0.1,
            model_max_retries=0,
            model_circuit_failure_threshold=2,
            model_circuit_cooldown_seconds=3,
        )
        dependencies = ResolverDependencies(
            resolve_question_context=lambda question, history: unresolved_context(
                question, "deterministic"
            ),
            unresolved_context=unresolved_context,
            build_messages=lambda *_args: [],
            response_format={},
            provider_options=lambda *_args: {},
            stream_completion=AsyncMock(
                return_value=({"content": "not json"}, {}, None)
            ),
            semantic_resolution=lambda *_args: None,
            notify=AsyncMock(),
            emit=capture_emit,
            perf_counter=lambda: 1.0,
            async_client=lambda **_kwargs: Client(),
            timeout=timeout,
            sleep=AsyncMock(),
            failure_reason=lambda exc: getattr(exc, "code", "error"),
            retryable_error=lambda _exc: False,
            error_category=lambda _exc: "error",
            retry_delay=lambda *_args: 0.0,
            audit_assistant=lambda assistant: assistant or {},
            record_failure=lambda *_args, **_kwargs: ({}, None),
            record_success=lambda _model_id: ({"status": "healthy"}, "recovered"),
            content_fingerprint=lambda content: f"fp:{len(content)}",
        )

        asyncio.run(
            resolve_conversation_turn(
                "继续",
                [{"role": "assistant", "content": "上文"}],
                settings,
                "run-protocol-recovery",
                None,
                health_model_id="model-a",
                health_recovery_trial=True,
                deps=dependencies,
            )
        )

        self.assertIn(
            (
                "model_circuit_recovered",
                ("run-protocol-recovery",),
                {"model_id": "model-a", "health": {"status": "healthy"}},
            ),
            emitted,
        )


if __name__ == "__main__":
    unittest.main()
