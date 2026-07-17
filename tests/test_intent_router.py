from __future__ import annotations

import asyncio
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app import agent as agent_module
from app.intent_router import route_question


class IntentRouterTests(unittest.TestCase):
    def test_routes_cmp_capability_example_with_default_range_and_high_risk(self):
        route = route_question(
            "分析一下 CMP 几台全不合格的潜在原因",
            current_date=date(2026, 7, 18),
        )

        self.assertEqual(route.intent, "capability_excursion")
        self.assertEqual(route.process_steps, ("CMP",))
        self.assertEqual(route.equipment_ids, ())
        self.assertEqual(route.time_range.start, "2026-04-20")
        self.assertEqual(route.time_range.end, "2026-07-18")
        self.assertEqual(route.time_range.source, "default_90_days")
        self.assertTrue(route.time_range.assumed)
        self.assertIn("get_process_capability", route.data_requirements)
        self.assertIn("get_recent_excursions", route.data_requirements)
        self.assertEqual(route.risk_level, "high")
        self.assertFalse(route.clarification_needed)

    def test_extracts_equipment_process_and_explicit_date_range(self):
        route = route_question(
            "检查 ETCH-04 从 2026-07-01 到 2026-07-05 的故障报警",
            current_date=date(2026, 7, 18),
        )

        self.assertEqual(route.intent, "equipment_fault")
        self.assertEqual(route.process_steps, ("ETCH",))
        self.assertEqual(route.equipment_ids, ("ETCH-04",))
        self.assertEqual(route.time_range.start, "2026-07-01")
        self.assertEqual(route.time_range.end, "2026-07-05")
        self.assertEqual(route.time_range.source, "explicit")
        self.assertFalse(route.time_range.assumed)

    def test_routes_supported_domain_intents(self):
        cases = (
            ("最近四周工厂良率下降趋势", "yield_decline", "get_yield_trend"),
            ("追踪批次 L260708-02460 的完整履历", "lot_trace", "query_manufacturing_data"),
            ("查询光刻设备恢复量产 SOP", "sop_lookup", "search_knowledge"),
            ("分析 CVD 颗粒缺陷 Pareto", "defect_analysis", "get_defect_pareto"),
            ("查看工厂总览和生产概况", "fab_overview", "get_fab_overview"),
        )

        for question, expected_intent, expected_requirement in cases:
            with self.subTest(question=question):
                route = route_question(question, current_date=date(2026, 7, 18))
                self.assertEqual(route.intent, expected_intent)
                self.assertIn(expected_requirement, route.data_requirements)

    def test_relative_range_is_inclusive(self):
        route = route_question("最近7天 CMP-03 Cpk", current_date=date(2026, 7, 18))

        self.assertEqual(route.time_range.start, "2026-07-12")
        self.assertEqual(route.time_range.end, "2026-07-18")
        self.assertEqual(route.time_range.source, "relative")

    def test_marks_close_conjoined_intents_as_ambiguous(self):
        route = route_question("比较设备健康和良率趋势", current_date=date(2026, 7, 18))

        self.assertEqual(route.intent, "ambiguous")
        self.assertEqual(set(route.candidate_intents[:2]), {"yield_decline", "equipment_fault"})
        self.assertTrue(route.clarification_needed)
        self.assertTrue(route.clarification_questions)
        self.assertIn("get_yield_trend", route.data_requirements)
        self.assertIn("get_equipment_health", route.data_requirements)

    def test_unknown_intent_requests_clarification_without_guessing_tools(self):
        route = route_question("帮我看看这个情况", current_date=date(2026, 7, 18))

        self.assertEqual(route.intent, "unknown")
        self.assertEqual(route.confidence, 0.0)
        self.assertEqual(route.data_requirements, ())
        self.assertTrue(route.clarification_needed)
        self.assertEqual(route.risk_level, "medium")

    def test_agent_loop_injects_and_returns_structured_route(self):
        captured: dict = {}
        progress_events: list[dict] = []

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            captured.update(request_payload)
            return ({"role": "assistant", "content": "路由测试完成"}, {"total_tokens": 3}, "route-response")

        async def progress(event: dict) -> None:
            progress_events.append(event)

        settings = SimpleNamespace(
            deepseek_api_key="test-key",
            deepseek_base_url="https://example.test",
            deepseek_model="test-model",
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
        ):
            result = asyncio.run(
                agent_module._run_agent_impl(
                    "分析 CMP-03 最近7天 Cpk",
                    [],
                    "run-intent-router-test",
                    progress,
                )
            )

        self.assertEqual(result["intent_route"]["intent"], "capability_excursion")
        self.assertEqual(result["intent_route"]["equipment_ids"], ("CMP-03",))
        routing_event = next(event for event in progress_events if event.get("stage") == "routing")
        self.assertEqual(routing_event["route"], result["intent_route"])
        routing_message = captured["messages"][1]
        self.assertEqual(routing_message["role"], "system")
        payload = json.loads(routing_message["content"].split("intent_route=", 1)[1])
        self.assertEqual(payload["intent"], "capability_excursion")
        self.assertEqual(payload["equipment_ids"], ["CMP-03"])


if __name__ == "__main__":
    unittest.main()
