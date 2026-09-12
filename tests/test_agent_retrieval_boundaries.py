from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app import agent
from app.evidence.validator import EvidenceObservation


class _AllowingGuard:
    def __init__(self):
        self.rounds: list[str] = []
        self.recorded: list[tuple[str, object, bool]] = []

    def begin_round(self):
        self.rounds.append("begin")

    def finish_round(self):
        self.rounds.append("finish")

    def check_call(self, _tool, _arguments):
        return SimpleNamespace(allowed=True, reason_code=None, message=None)

    def record_result(self, tool, result, success):
        self.recorded.append((tool, result, success))


class AgentRetrievalBoundaryTests(unittest.TestCase):
    def test_facade_uses_live_handlers_emit_and_notify_dependencies(self):
        calls: list[dict] = []
        emitted = Mock()
        notify = AsyncMock()
        guard = _AllowingGuard()
        source = {"reference_id": "KB-1", "source_type": "knowledge", "retrieval": {"confidence": "high"}}
        with patch.dict(agent.TOOL_HANDLERS, {"search_knowledge": lambda **kwargs: calls.append(kwargs) or [source]}), \
             patch("app.agent.emit", emitted), patch("app.agent._notify", notify):
            decision = asyncio.run(agent._prefetch_general_knowledge(
                "GaN 基础", "retrieval-boundary", guard, [], [], {}, None,
            ))
        self.assertEqual(calls, [
            {"query": "GaN 基础", "limit": 10, "source_types": ["personal"]},
            {"query": "GaN 基础", "limit": 10, "source_types": ["knowledge"]},
        ])
        self.assertEqual(decision.selected_reference_ids, ("KB-1",))
        self.assertEqual(guard.rounds, ["begin", "finish"])
        self.assertTrue(any(call.args[0] == "tool_call_started" for call in emitted.call_args_list))
        self.assertTrue(any(call.args[0] == "knowledge_retrieval_decided" for call in emitted.call_args_list))
        self.assertEqual(notify.await_count, 5)

    def test_original_rewritten_scope_order_and_source_filtering_are_preserved(self):
        calls: list[dict] = []
        guard = _AllowingGuard()

        def search_knowledge(**arguments):
            calls.append(arguments)
            scope = arguments["source_types"][0]
            return [
                {"reference_id": f"{scope}-{arguments['query']}", "source_type": scope,
                 "retrieval": {"confidence": "high"}},
                {"reference_id": f"LOW-{scope}", "source_type": scope,
                 "retrieval": {"confidence": "low"}},
            ]

        sources: dict[str, dict] = {}
        with patch.dict(agent.TOOL_HANDLERS, {"search_knowledge": search_knowledge}), patch("app.agent.emit"):
            decision = asyncio.run(agent._prefetch_general_knowledge(
                "S 器件故障", "retrieval-order", guard, [], [], sources, None,
            ))
        expected_queries = ["S 器件故障"] * 3 + ["Si 器件故障"] * 3
        self.assertEqual([call["query"] for call in calls], expected_queries)
        self.assertEqual([call["source_types"][0] for call in calls], ["personal", "knowledge", "case"] * 2)
        self.assertEqual(guard.rounds, ["begin", "finish", "begin", "finish"])
        self.assertEqual(len(sources), 6)
        self.assertFalse(any(reference.startswith("LOW-") for reference in sources))
        self.assertEqual(decision.rewritten_query, "Si 器件故障")

    def test_empty_or_error_retrieval_preserves_model_fallback_decision(self):
        guard = _AllowingGuard()
        with patch.dict(agent.TOOL_HANDLERS, {"search_knowledge": lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline"))}), patch("app.agent.emit"):
            decision = asyncio.run(agent._prefetch_general_knowledge(
                "GaN 原理", "retrieval-error", guard, [], [], {}, None,
            ))
        self.assertEqual((decision.state, decision.reason, decision.model_knowledge_allowed), (
            "MODEL_ONLY_FALLBACK", "search_unavailable", True,
        ))
        self.assertEqual([attempt["status"] for attempt in decision.attempts], ["error", "error"])

    def test_normalize_disclosure_and_legacy_sop_fallback_facades_are_equivalent(self):
        answer = "```json\n{\"tool_calls\":[{\"function\":{\"name\":\"submit_analysis\",\"arguments\":\"{\\\"content\\\":\\\"结论\\\"}\"}}]}\n```"
        self.assertEqual(agent._normalize_general_knowledge_answer(answer), "结论")
        self.assertTrue(agent._has_knowledge_fallback_disclosure(
            "个人知识库和工厂知识库均未检索到可用内容，以下为模型通用知识，仅供参考。"
        ))
        route = SimpleNamespace(intent="sop_lookup")
        empty = EvidenceObservation("search_knowledge", {}, "success", [])
        self.assertEqual(
            agent._knowledge_fallback_state(route, [empty], {}),
            {"used": True, "reason": "search_empty", "disclosure": agent.MODEL_KNOWLEDGE_DISCLOSURE},
        )


if __name__ == "__main__":
    unittest.main()
