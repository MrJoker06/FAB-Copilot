from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app import agent, agent_tools


class AgentModuleBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_agent_keeps_legacy_tool_catalog_exports(self):
        self.assertIs(agent.TOOLS, agent_tools.TOOLS)
        self.assertIs(agent.TOOL_HANDLERS, agent_tools.TOOL_HANDLERS)
        self.assertIs(agent.search_agent_knowledge, agent_tools.search_agent_knowledge)
        tool_names = [item["function"]["name"] for item in agent.TOOLS]
        self.assertEqual(len(tool_names), len(set(tool_names)))
        self.assertEqual(
            set(agent.TOOL_HANDLERS), set(tool_names) - {"submit_analysis"}
        )

    async def test_stream_compatibility_wrapper_injects_live_agent_callbacks(self):
        expected = (
            {"role": "assistant", "content": "ok"},
            {"total_tokens": 1},
            "response-1",
        )
        delegate = AsyncMock(return_value=expected)
        progress = object()
        stream_state = {"answer_emitted": False}
        with patch("app.agent.stream_completion", new=delegate):
            result = await agent._stream_completion(
                object(),
                "https://model.test/v1/chat/completions",
                {"X-Test": "1"},
                {"model": "test"},
                progress,
                stream_state,
            )
        self.assertEqual(result, expected)
        delegate.assert_awaited_once_with(
            unittest.mock.ANY,
            "https://model.test/v1/chat/completions",
            {"X-Test": "1"},
            {"model": "test"},
            progress,
            stream_state,
            notify=agent._notify,
            disclosure_checker=agent._has_knowledge_fallback_disclosure,
        )

    def test_audit_compatibility_wrapper_still_removes_reasoning(self):
        assistant = {
            "role": "assistant",
            "content": "answer",
            "reasoning_content": "private",
        }
        self.assertEqual(
            agent._audit_assistant(assistant),
            {"role": "assistant", "content": "answer"},
        )


if __name__ == "__main__":
    unittest.main()
