from __future__ import annotations

import asyncio
import json
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


def _plan(question: str):
    route = route_question(question, current_date=date(2026, 7, 18))
    return create_execution_plan(question, route, select_playbook(route))


class ToolLoopGuardTests(unittest.TestCase):
    def test_duplicate_arguments_are_blocked_before_execution(self):
        guard = ToolLoopGuard(_plan("分析 CMP-03 最近7天 Cpk 不合格"))
        arguments = {"start": "2026-07-12", "end": "2026-07-18", "process_step": "CMP"}

        first = guard.check_call("get_process_capability", arguments)
        second = guard.check_call("get_process_capability", arguments)

        self.assertTrue(first.allowed)
        self.assertFalse(second.allowed)
        self.assertEqual(second.reason_code, "duplicate_arguments")
        self.assertEqual(guard.summary()["total_calls"], 1)
        self.assertEqual(guard.summary()["blocked_reasons"], {"duplicate_arguments": 1})

    def test_total_and_per_tool_limits_are_enforced(self):
        generic_plan = _plan("分析 CMP 划伤缺陷 Pareto")
        per_tool_guard = ToolLoopGuard(generic_plan)
        for limit in (5, 10, 15):
            self.assertTrue(per_tool_guard.check_call("get_defect_pareto", {"limit": limit}).allowed)
        blocked = per_tool_guard.check_call("get_defect_pareto", {"limit": 20})
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason_code, "per_tool_budget_exhausted")

        budget = replace(generic_plan.budget, max_tool_calls=2, per_tool_limits={"*": 5})
        total_guard = ToolLoopGuard(replace(generic_plan, budget=budget))
        self.assertTrue(total_guard.check_call("get_fab_overview", {"start": "2026-07-01"}).allowed)
        self.assertTrue(total_guard.check_call("get_equipment_health", {"start": "2026-07-01"}).allowed)
        blocked = total_guard.check_call("get_yield_trend", {"start": "2026-07-01"})
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason_code, "total_tool_budget_exhausted")
        self.assertTrue(total_guard.force_synthesis)

    def test_ready_plan_blocks_unplanned_tools_but_generic_plan_allows_them(self):
        ready_guard = ToolLoopGuard(_plan("关于目前的制造数据你有什么改进建议"))

        blocked = ready_guard.check_call("search_knowledge", {"query": "改善建议"})

        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason_code, "unplanned_tool")
        self.assertEqual(ready_guard.total_calls, 0)

        generic_guard = ToolLoopGuard(_plan("分析 CMP 划伤缺陷 Pareto"))
        self.assertTrue(generic_guard.check_call("search_knowledge", {"query": "CMP 划伤"}).allowed)

    def test_repeated_evidence_triggers_no_progress_synthesis(self):
        guard = ToolLoopGuard(_plan("分析 CMP 划伤缺陷 Pareto"))

        guard.begin_round()
        self.assertTrue(guard.check_call("get_defect_pareto", {"limit": 5}).allowed)
        self.assertTrue(guard.record_result("get_defect_pareto", [{"defect_type": "Scratch"}], True))
        self.assertFalse(guard.finish_round())

        for limit in (10, 15):
            guard.begin_round()
            self.assertTrue(guard.check_call("get_defect_pareto", {"limit": limit}).allowed)
            self.assertFalse(guard.record_result("get_defect_pareto", [{"defect_type": "Scratch"}], True))
            guard.finish_round()

        self.assertTrue(guard.force_synthesis)
        self.assertEqual(guard.stop_reason, "no_progress")
        self.assertEqual(guard.summary()["unique_evidence_results"], 1)

    def test_clarification_plan_disables_tools_immediately(self):
        plan = _plan("分析 Cpk 不合格")
        guard = ToolLoopGuard(plan)

        decision = guard.check_call("get_process_capability", {})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, "synthesis_only")
        self.assertEqual(guard.stop_reason, "clarification_required")
        self.assertEqual(guard.summary()["total_calls"], 0)

        with (
            patch("app.agent.fab_overview", side_effect=AssertionError("clarification must not query data")),
            patch("app.agent.equipment_health", side_effect=AssertionError("clarification must not query data")),
        ):
            result = agent_module._offline_answer(
                "分析 Cpk 不合格",
                route_question("分析 Cpk 不合格", current_date=date(2026, 7, 18)),
                select_playbook(route_question("分析 Cpk 不合格", current_date=date(2026, 7, 18))),
                plan,
                ToolLoopGuard(plan),
            )
        self.assertEqual(result["tool_trace"], [])
        self.assertIn("请先补充", result["answer"])

    def test_generic_agent_loop_still_blocks_duplicates_and_switches_to_synthesis(self):
        requests: list[dict] = []
        events: list[dict] = []
        handler_calls: list[dict] = []
        model_round = 0

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal model_round
            model_round += 1
            requests.append(request_payload)
            if model_round <= 3:
                arguments = {
                    "start": "2026-07-12",
                    "end": "2026-07-18",
                    "process_step": "CMP",
                }
                return (
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": f"call-{model_round}",
                            "type": "function",
                            "function": {
                                "name": "get_process_capability",
                                "arguments": json.dumps(arguments),
                            },
                        }],
                    },
                    {"total_tokens": 5},
                    f"response-{model_round}",
                )
            return ({"role": "assistant", "content": "已有证据不足，已停止重复查询。"}, {"total_tokens": 5}, "final")

        async def progress(event: dict) -> None:
            events.append(event)

        def fake_handler(**arguments):
            handler_calls.append(arguments)
            return [{"equipment_id": "CMP-03", "cpk": 0.91}]

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"get_process_capability": fake_handler}),
        ):
            result = asyncio.run(
                agent_module._run_agent_impl(
                    "分析 CMP 划伤缺陷 Pareto",
                    [],
                    "run-loop-guard-test",
                    progress,
                )
            )

        self.assertEqual(len(handler_calls), 1)
        self.assertEqual([item["status"] for item in result["tool_trace"]], ["ok", "blocked", "blocked"])
        self.assertEqual(result["loop_guard"]["stop_reason"], "no_progress")
        self.assertEqual(result["loop_guard"]["total_calls"], 1)
        self.assertEqual(result["loop_guard"]["blocked_calls"], 2)
        self.assertEqual([request["tool_choice"] for request in requests[:3]], ["auto", "auto", "auto"])
        self.assertEqual(requests[-1]["tool_choice"], "none")
        self.assertNotIn("max_tokens", requests[-1])
        self.assertIn(
            "get_process_capability",
            [tool["function"]["name"] for tool in requests[-1]["tools"]],
        )
        self.assertEqual(sum(event.get("status") == "blocked" for event in events), 2)


if __name__ == "__main__":
    unittest.main()
