from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app import agent as agent_module
from app.manufacturing.playbooks import select_playbook
from app.intent_router import route_question
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.planner import create_execution_plan


def _plan():
    question = "分析 CMP-03 最近7天 Cpk 不合格"
    route = route_question(question, current_date=date(2026, 8, 23))
    return create_execution_plan(question, route, select_playbook(route))


class ReadyPlanExecutionTests(unittest.TestCase):
    def test_reference_counts_separate_knowledge_tool_evidence_and_total(self):
        counts = agent_module._trace_reference_counts({
            "answer_synthesis": {"source_refs": ["TOOL:S01", "KB-1", "KB-1", "MODEL_GENERAL_KNOWLEDGE"]},
            "sources": [{"reference_id": "CASE-1"}, {"reference_id": "KB-1"}],
        })
        self.assertEqual(counts, {
            "knowledge_source_count": 2,
            "tool_evidence_count": 1,
            "total_reference_count": 3,
        })

    def test_run_finished_publishes_unambiguous_reference_counts(self):
        emitted: list[tuple[str, dict]] = []

        async def fake_impl(*_args, **_kwargs):
            return {
                "answer": "完成",
                "tool_trace": [
                    {"tool": "get_process_capability", "status": "ok", "duration_ms": 8},
                    {"tool": "search_knowledge", "status": "ok", "duration_ms": 3},
                ],
                "sources": [{"reference_id": "KB-1"}],
                "answer_synthesis": {"source_refs": ["TOOL:S01", "KB-1"]},
                "intent_route": {},
                "context_resolution": {},
            }

        def capture(event_type: str, _run_id: str, **fields) -> None:
            emitted.append((event_type, fields))

        with patch("app.agent._run_agent_impl", new=fake_impl), patch("app.agent.emit", new=capture):
            result = asyncio.run(agent_module.run_agent("分析 CMP"))

        finished = next(fields for event, fields in emitted if event == "agent_run_finished")
        self.assertEqual(
            {key: finished[key] for key in ("knowledge_source_count", "tool_evidence_count", "total_reference_count")},
            {"knowledge_source_count": 1, "tool_evidence_count": 1, "total_reference_count": 2},
        )
        self.assertEqual((finished["tool_duration_ms"], finished["retrieval_duration_ms"]), (8.0, 3.0))
        self.assertEqual(result["trace_semantics"]["total_reference_count"], 2)

    def test_ready_plan_executes_exact_steps_in_dependency_order(self):
        plan = _plan()
        calls: list[tuple[str, dict]] = []
        events: list[dict] = []

        def handler(name, result):
            def execute(**arguments):
                calls.append((name, arguments))
                return result
            return execute

        async def progress(event: dict) -> None:
            events.append(event)

        handlers = {
            "get_process_capability": handler("get_process_capability", [{
                "equipment_id": "CMP-03", "samples": 120, "mean_value": 100.0,
                "sigma": 1.0, "cpk": 1.1, "metric_name": "Thickness",
                "metric_unit": "nm", "spec_lsl": 95.0, "spec_usl": 105.0,
            }]),
            "get_recent_excursions": handler("get_recent_excursions", []),
            "get_sensor_summary": handler("get_sensor_summary", []),
            "search_knowledge": handler("search_knowledge", []),
        }
        with patch.dict(agent_module.TOOL_HANDLERS, handlers), patch("app.agent.emit"):
            trace, observations, sources = asyncio.run(agent_module._execute_ready_plan(
                plan,
                ToolLoopGuard(plan),
                "ready-order-test",
                progress,
            ))

        self.assertEqual([name for name, _ in calls], [step.tool for step in plan.steps])
        self.assertEqual([arguments for _, arguments in calls], [step.parameters for step in plan.steps])
        self.assertEqual([item["plan_step_id"] for item in trace], [step.step_id for step in plan.steps])
        self.assertEqual([item.source_ref for item in observations], [f"TOOL:{step.step_id}" for step in plan.steps])
        self.assertTrue(all(item["execution_mode"] == "deterministic" for item in trace))
        self.assertEqual(sources, {})
        self.assertFalse(any(event.get("event") == "answer_delta" for event in events))

    def test_failed_dependency_blocks_downstream_steps_without_calling_handlers(self):
        plan = _plan()
        calls: list[str] = []

        def fail_first(**arguments):
            calls.append("get_process_capability")
            raise RuntimeError("synthetic capability failure")

        def forbidden(**arguments):
            raise AssertionError("dependent handler must not run")

        handlers = {
            "get_process_capability": fail_first,
            "get_recent_excursions": forbidden,
            "get_sensor_summary": forbidden,
            "search_knowledge": forbidden,
        }
        with patch.dict(agent_module.TOOL_HANDLERS, handlers), patch("app.agent.emit"):
            trace, observations, _ = asyncio.run(agent_module._execute_ready_plan(
                plan,
                ToolLoopGuard(plan),
                "ready-dependency-test",
                None,
            ))

        self.assertEqual(calls, ["get_process_capability"])
        self.assertEqual([item["status"] for item in trace], ["error", "blocked", "blocked", "blocked"])
        self.assertTrue(all(item.get("error_code") == "dependency_failed" for item in trace[1:]))
        self.assertEqual([item.status for item in observations], ["error", "blocked", "blocked", "blocked"])

    def test_invalid_ready_plan_graph_fails_closed_before_execution(self):
        plan = _plan()
        first = replace(plan.steps[0], depends_on=(plan.steps[-1].step_id,))
        cyclic = replace(plan, steps=(first, *plan.steps[1:]))

        with self.assertRaisesRegex(ValueError, "循环依赖"):
            agent_module._ready_step_order(cyclic)

        unknown = replace(plan, steps=(replace(plan.steps[0], depends_on=("S99",)), *plan.steps[1:]))
        with self.assertRaisesRegex(ValueError, "未知依赖"):
            agent_module._ready_step_order(unknown)

    def test_ready_plan_still_executes_when_model_is_not_configured(self):
        calls: list[str] = []

        def handler(name):
            def execute(**arguments):
                calls.append(name)
                return []
            return execute

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(
                provider="test", api_key="", base_url="https://example.test", model="test-model",
            ),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        handlers = {
            name: handler(name)
            for name in (
                "get_process_capability", "get_recent_excursions",
                "get_sensor_summary", "search_knowledge",
            )
        }
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", side_effect=AssertionError("model must not be called")),
            patch.dict(agent_module.TOOL_HANDLERS, handlers),
            patch("app.agent.emit"),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "分析 CMP-03 最近7天 Cpk 不合格",
                [],
                "ready-no-model-test",
            ))

        self.assertEqual(calls, [
            "get_process_capability", "get_recent_excursions",
            "get_sensor_summary", "search_knowledge",
        ])
        self.assertEqual(result["execution_mode"], "deterministic_ready_plan")
        self.assertEqual(result["model_tool_selection_calls"], 0)
        self.assertEqual(result["mode"], "deterministic-fallback")


if __name__ == "__main__":
    unittest.main()
