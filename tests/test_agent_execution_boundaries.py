from __future__ import annotations

import asyncio
import unittest
from datetime import date
from unittest.mock import patch

from app import agent
from app.agent_runtime.execution.failure import decide_model_failure
from app.manufacturing.playbooks import select_playbook
from app.intent_router import route_question
from app.loop_guard import ToolLoopGuard
from app.planner import create_execution_plan


class AgentExecutionBoundaryTests(unittest.TestCase):
    def test_ready_facades_delegate_to_runtime_with_live_module_dependencies(self):
        plan = create_execution_plan(
            "分析 CMP-03 最近7天 Cpk 不合格",
            route_question("分析 CMP-03 最近7天 Cpk 不合格", current_date=date(2026, 8, 23)),
            select_playbook(route_question("分析 CMP-03 最近7天 Cpk 不合格", current_date=date(2026, 8, 23))),
        )
        calls: list[str] = []
        handlers = {
            step.tool: (lambda tool: lambda **_kwargs: calls.append(tool) or [])(step.tool)
            for step in plan.steps
        }
        with patch.dict(agent.TOOL_HANDLERS, handlers), patch("app.agent.emit"):
            asyncio.run(agent._execute_ready_plan(plan, ToolLoopGuard(plan), "boundary", None))
        self.assertEqual(calls, [step.tool for step in plan.steps])

    def test_ready_order_preserves_exact_invalid_graph_errors(self):
        plan = create_execution_plan(
            "分析 CMP-03 最近7天 Cpk 不合格",
            route_question("分析 CMP-03 最近7天 Cpk 不合格", current_date=date(2026, 8, 23)),
            select_playbook(route_question("分析 CMP-03 最近7天 Cpk 不合格", current_date=date(2026, 8, 23))),
        )
        first = plan.steps[0]
        duplicate = type(first)(**{**first.__dict__, "step_id": first.step_id})
        invalid = type(plan)(**{**plan.__dict__, "steps": (first, duplicate)})
        with self.assertRaisesRegex(ValueError, "^ready 执行计划包含重复 step_id$"):
            agent._ready_step_order(invalid)

    def test_failure_decision_preserves_retry_and_first_body_contract(self):
        retry = decide_model_failure(
            availability_failure=True, answer_emitted=False, attempt=1, retry_budget=1
        )
        exhausted = decide_model_failure(
            availability_failure=True, answer_emitted=False, attempt=2, retry_budget=1
        )
        non_retryable = decide_model_failure(
            availability_failure=False, answer_emitted=False, attempt=1, retry_budget=2
        )
        after_body = decide_model_failure(
            availability_failure=True, answer_emitted=True, attempt=1, retry_budget=2
        )
        self.assertEqual((retry.retryable, retry.will_retry, retry.fallback_before_first_body), (True, True, True))
        self.assertEqual((exhausted.retryable, exhausted.will_retry, exhausted.fallback_before_first_body), (True, False, True))
        self.assertEqual((non_retryable.retryable, non_retryable.will_retry, non_retryable.fallback_before_first_body), (False, False, False))
        self.assertEqual((after_body.retryable, after_body.will_retry, after_body.fallback_before_first_body), (False, False, False))


if __name__ == "__main__":
    unittest.main()
