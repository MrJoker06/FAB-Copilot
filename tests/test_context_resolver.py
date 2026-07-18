from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import agent as agent_module
from app.answer_synthesizer import MODEL_KNOWLEDGE_REF
from app.context_resolver import resolve_question_context
from app.intent_router import route_question


INITIAL_QUESTION = "GaN器件和纯Si器件的差异"
CLARIFICATION = """为了继续，请选择分析方向：
- 比较制造指标，例如 Cpk 或良率
- 指定工艺站点或设备
- 指定时间范围
- 结合历史案例或 SOP 规范
- 先展示两类器件在晶圆厂内的基本工艺路线差异（需要调用知识库）"""


def _settings():
    return SimpleNamespace(
        deepseek_api_key="test-key",
        deepseek_base_url="https://example.test",
        deepseek_model="test-model",
        api_timeout_seconds=5,
        model_max_retries=0,
        model_retry_base_seconds=0.05,
    )


class ContextResolverTests(unittest.TestCase):
    def test_last_option_resolves_against_previous_clarification(self):
        resolution = resolve_question_context(
            "最后一点",
            [
                {"role": "user", "content": INITIAL_QUESTION},
                {"role": "assistant", "content": CLARIFICATION},
            ],
        )

        self.assertTrue(resolution.applied)
        self.assertEqual(resolution.strategy, "ordinal_selection")
        self.assertIn(INITIAL_QUESTION, resolution.resolved_question)
        self.assertIn("基本工艺路线差异", resolution.selected_context)
        self.assertEqual(route_question(resolution.resolved_question).intent, "sop_lookup")

    def test_continue_resolves_previous_declared_action(self):
        resolution = resolve_question_context(
            "为什么没有继续",
            [
                {"role": "user", "content": INITIAL_QUESTION},
                {"role": "assistant", "content": CLARIFICATION},
                {"role": "user", "content": "最后一点"},
                {"role": "assistant", "content": "好的，我先调用知识库查找 GaN 与 Si 的基本工艺路线差异。"},
            ],
        )

        self.assertTrue(resolution.applied)
        self.assertEqual(resolution.strategy, "continue_previous_action")
        self.assertIn("调用知识库", resolution.selected_context)
        self.assertEqual(route_question(resolution.resolved_question).intent, "sop_lookup")

    def test_context_dependent_phrase_without_history_is_not_guessed(self):
        resolution = resolve_question_context("最后一点", [])

        self.assertFalse(resolution.applied)
        self.assertEqual(resolution.resolved_question, "最后一点")

    def test_agent_does_not_override_explicit_current_intent_with_history(self):
        history = [
            {"role": "user", "content": INITIAL_QUESTION},
            {"role": "assistant", "content": CLARIFICATION},
        ]
        captured: dict = {}

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            captured.update(request_payload)
            return ({"role": "assistant", "content": "良率分析完成"}, {"total_tokens": 3}, "explicit-route")

        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", new=fake_stream),
        ):
            result = asyncio.run(
                agent_module._run_agent_impl(
                    "最后一点先放下，改为分析最近四周良率",
                    history,
                    "run-explicit-current-intent-test",
                )
            )

        self.assertFalse(result["context_resolution"]["applied"])
        self.assertEqual(result["intent_route"]["intent"], "yield_decline")
        self.assertNotIn("context_resolution=", "\n".join(item["content"] for item in captured["messages"]))

    def test_agent_executes_knowledge_tool_for_selected_last_option(self):
        history = [
            {"role": "user", "content": INITIAL_QUESTION},
            {"role": "assistant", "content": CLARIFICATION},
        ]
        resolved = resolve_question_context("最后一点", history).resolved_question
        source = {
            "reference_id": "KB-CONTEXT-001",
            "source_type": "knowledge",
            "source": "器件工艺路线概览",
            "title": "GaN 与 Si 器件工艺路线",
            "section": "基础流程",
            "content": "GaN 与 Si 器件需要按材料体系和器件结构区分工艺路线。",
            "retrieval": {"confidence": "high", "final_score": 0.95},
            "status": "Effective",
            "version": "1.0",
            "effective_date": "2026-01-01",
            "owner": "Process Integration",
            "process_steps": ["LITHO", "ETCH", "CVD"],
            "equipment_families": ["LITHO", "ETCH", "CVD"],
        }
        calls = 0

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            if calls == 1:
                return (
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "context-search",
                            "type": "function",
                            "function": {
                                "name": "search_knowledge",
                                "arguments": json.dumps({
                                    "query": resolved,
                                    "limit": 10,
                                    "source_types": ["personal", "knowledge"],
                                }, ensure_ascii=False),
                            },
                        }],
                    },
                    {"total_tokens": 10},
                    "context-tool-response",
                )
            return (
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "context-submit",
                        "type": "function",
                        "function": {
                            "name": "submit_analysis",
                            "arguments": json.dumps({
                                "conclusion": "已根据正式知识整理两类器件的工艺路线差异。",
                                "facts": [{
                                    "statement": "知识文档覆盖 GaN 与 Si 器件的基础流程差异。",
                                    "evidence_refs": ["KB-CONTEXT-001"],
                                }],
                                "inferences": [],
                                "hypotheses": [],
                                "recommendations": [],
                                "limitations": [],
                            }, ensure_ascii=False),
                        },
                    }],
                },
                {"total_tokens": 10},
                "context-submit-response",
            )

        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: [source]}),
        ):
            result = asyncio.run(
                agent_module._run_agent_impl("最后一点", history, "run-context-follow-up-test")
            )

        self.assertEqual(result["context_resolution"]["strategy"], "ordinal_selection")
        self.assertEqual(result["intent_route"]["intent"], "sop_lookup")
        self.assertEqual(result["execution_plan"]["status"], "ready")
        self.assertEqual([item["tool"] for item in result["tool_trace"]], ["search_knowledge"])
        self.assertEqual(result["tool_trace"][0]["status"], "ok")
        self.assertIn("KB-CONTEXT-001", {item["reference_id"] for item in result["sources"]})

    def test_unresolved_clarification_never_calls_model(self):
        model_call = AsyncMock(side_effect=AssertionError("clarification path must not call model"))
        progress_events: list[dict] = []

        async def progress(event: dict) -> None:
            progress_events.append(event)

        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", model_call),
        ):
            result = asyncio.run(
                agent_module._run_agent_impl("帮我看看这个情况", [], "run-context-clarification-test", progress)
            )

        model_call.assert_not_awaited()
        self.assertEqual(result["mode"], "clarification")
        self.assertEqual(result["model"], "deterministic-router")
        self.assertEqual(result["tool_trace"], [])
        self.assertEqual(result["execution_plan"]["status"], "clarification_required")
        self.assertNotIn("```json", result["answer"])
        self.assertIn("5. 查询 SOP、正式知识", result["answer"])
        follow_up = resolve_question_context(
            "最后一点",
            [
                {"role": "user", "content": "帮我比较两种器件"},
                {"role": "assistant", "content": result["answer"]},
            ],
        )
        self.assertTrue(follow_up.applied)
        self.assertEqual(route_question(follow_up.resolved_question).intent, "sop_lookup")
        self.assertTrue(any(item.get("stage") == "clarification" for item in progress_events))

    def test_empty_knowledge_results_fall_back_to_disclosed_model_knowledge(self):
        history = [
            {"role": "user", "content": INITIAL_QUESTION},
            {"role": "assistant", "content": CLARIFICATION},
        ]
        progress_events: list[dict] = []
        requests: list[dict] = []
        round_number = 0

        async def progress(event: dict) -> None:
            progress_events.append(event)

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal round_number
            round_number += 1
            requests.append(request_payload)
            if round_number <= 2:
                source_types = ["personal", "knowledge"] if round_number == 1 else ["case"]
                return (
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": f"empty-search-{round_number}",
                            "type": "function",
                            "function": {
                                "name": "search_knowledge",
                                "arguments": json.dumps({
                                    "query": INITIAL_QUESTION,
                                    "limit": 10,
                                    "source_types": source_types,
                                }, ensure_ascii=False),
                            },
                        }],
                    },
                    {"total_tokens": 5},
                    f"empty-search-response-{round_number}",
                )
            submission = {
                "conclusion": "GaN 与 Si 器件的差异主要来自材料特性和器件结构。",
                "facts": [],
                "inferences": [{
                    "statement": "GaN 的宽禁带和高击穿场强通常适合高压与高频功率场景。",
                    "evidence_refs": [MODEL_KNOWLEDGE_REF],
                }],
                "hypotheses": [],
                "recommendations": [],
                "limitations": [],
                "source_refs": [MODEL_KNOWLEDGE_REF],
            }
            return (
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "fallback-submit",
                        "type": "function",
                        "function": {
                            "name": "submit_analysis",
                            "arguments": json.dumps(submission, ensure_ascii=False),
                        },
                    }],
                },
                {"total_tokens": 8},
                "fallback-submit-response",
            )

        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: []}),
        ):
            result = asyncio.run(
                agent_module._run_agent_impl("最后一点", history, "run-knowledge-fallback-test", progress)
            )

        self.assertTrue(result["knowledge_fallback"]["used"])
        self.assertEqual(result["knowledge_fallback"]["reason"], "search_empty")
        self.assertEqual(len(result["tool_trace"]), 2)
        self.assertTrue(all(item["rows"] == 0 for item in result["tool_trace"]))
        self.assertIn("知识库未检索到相关内容", result["answer"])
        self.assertIn("GaN 的宽禁带", result["answer"])
        final_prompt = "\n".join(
            item.get("content", "")
            for item in requests[-1]["messages"]
            if item.get("role") == "system"
        )
        self.assertIn(MODEL_KNOWLEDGE_REF, final_prompt)
        self.assertTrue(any(item.get("stage") == "knowledge_fallback" for item in progress_events))


if __name__ == "__main__":
    unittest.main()
