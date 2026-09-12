from __future__ import annotations

import asyncio
import unittest
from datetime import date
from unittest.mock import patch

from app import agent, agent_tools
from app.agent_runtime.tools import catalog, registry
from app.agent_runtime.tools.executor import (
    execute_registered_tool,
    parse_tool_arguments,
)
from app.manufacturing.playbooks import select_playbook
from app.intent_router import route_question
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.planner import create_execution_plan


class AgentToolRuntimeBoundaryTests(unittest.TestCase):
    def test_compatibility_exports_are_the_canonical_runtime_objects(self):
        self.assertIs(agent_tools.TOOLS, catalog.TOOLS)
        self.assertIs(agent_tools.TOOL_HANDLERS, registry.TOOL_HANDLERS)
        self.assertIs(agent.TOOLS, catalog.TOOLS)
        self.assertIs(agent.TOOL_HANDLERS, registry.TOOL_HANDLERS)
        self.assertIs(agent.search_agent_knowledge, registry.search_agent_knowledge)
        self.assertIs(agent_tools._schema, catalog._schema)
        self.assertIs(agent_tools.DATE_PROPERTIES, catalog.DATE_PROPERTIES)

    def test_catalog_handlers_match_all_non_synthesis_tool_names(self):
        names = [tool["function"]["name"] for tool in catalog.TOOLS]
        self.assertEqual(names[-1], "submit_analysis")
        self.assertEqual(set(registry.TOOL_HANDLERS), set(names[:-1]))

    def test_parser_retains_legacy_default_and_error_semantics(self):
        valid = parse_tool_arguments('{"limit": 3}')
        default = parse_tool_arguments(None)
        malformed = parse_tool_arguments("{")
        non_object = parse_tool_arguments("[]")
        truncated = parse_tool_arguments("x" * 1100)

        self.assertEqual(valid.arguments, {"limit": 3})
        self.assertIsNone(valid.error)
        self.assertEqual(default.arguments, {})
        self.assertIsNone(default.error)
        self.assertEqual(malformed.arguments, {"_raw": "{"})
        self.assertIsInstance(malformed.error, Exception)
        self.assertEqual(non_object.arguments, {"_raw": "[]"})
        self.assertEqual(str(non_object.error), "工具参数必须是 JSON 对象")
        self.assertEqual(len(truncated.arguments["_raw"]), 1000)
        self.assertIsInstance(truncated.error, Exception)

    def test_executor_preserves_kwargs_result_identity_and_unknown_error(self):
        expected = {"rows": []}
        captured: list[dict] = []

        def handler(**kwargs):
            captured.append(kwargs)
            return expected

        arguments = {"equipment_id": "CMP-03"}
        self.assertIs(
            execute_registered_tool("tool", arguments, {"tool": handler}),
            expected,
        )
        self.assertEqual(captured, [arguments])
        with self.assertRaisesRegex(ValueError, "^未知工具: missing$"):
            execute_registered_tool("missing", {}, {})

    def test_agent_wrapper_and_ready_execution_resolve_live_registry(self):
        question = "分析 CMP-03 最近7天 Cpk 不合格"
        route = route_question(question, current_date=date(2026, 8, 23))
        plan = create_execution_plan(question, route, select_playbook(route))
        calls: list[tuple[str, dict]] = []

        def handler(name: str):
            def execute(**arguments):
                calls.append((name, arguments))
                return []

            return execute

        sentinel = {"direct": True}
        handlers = {step.tool: handler(step.tool) for step in plan.steps}
        handlers["runtime-direct"] = lambda **kwargs: sentinel
        with patch.dict(agent.TOOL_HANDLERS, handlers), patch("app.agent.emit"):
            self.assertIs(
                agent._execute_registered_tool("runtime-direct", {"value": 1}),
                sentinel,
            )
            asyncio.run(
                agent._execute_ready_plan(
                    plan, ToolLoopGuard(plan), "runtime-tools", None
                )
            )

        self.assertEqual(
            [name for name, _ in calls], [step.tool for step in plan.steps]
        )
        self.assertEqual(
            [arguments for _, arguments in calls],
            [step.parameters for step in plan.steps],
        )


if __name__ == "__main__":
    unittest.main()
