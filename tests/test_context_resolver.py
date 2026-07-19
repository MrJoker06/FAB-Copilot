from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import agent as agent_module
from app.answer_synthesizer import MODEL_KNOWLEDGE_REF
from app.context_resolver import (
    build_contextualizer_messages,
    resolve_question_context,
    semantic_context_resolution,
)
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


def _context_response(
    relation: str,
    resolved_question: str,
    topic_anchor: str = "",
    confidence: float = 0.95,
    intent_hint: str = "unclear",
) -> tuple[dict, dict, str]:
    return (
        {
            "role": "assistant",
            "content": json.dumps({
                "relation": relation,
                "resolved_question": resolved_question,
                "topic_anchor": topic_anchor,
                "confidence": confidence,
                "intent_hint": intent_hint,
            }, ensure_ascii=False),
        },
        {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
        "context-response",
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

    def test_context_dependent_phrase_without_history_is_not_guessed(self):
        resolution = resolve_question_context("最后一点", [])

        self.assertFalse(resolution.applied)
        self.assertEqual(resolution.resolved_question, "最后一点")

    def test_free_text_followups_are_not_resolved_by_phrase_rules(self):
        history = [
            {"role": "user", "content": "GaN 器件相对于 Si 器件的优势"},
            {"role": "assistant", "content": "已说明材料与器件特性。"},
        ]
        for question in ("换个角度解释", "倘若目标材料改成 SiC 会怎样", "接着分析"):
            with self.subTest(question=question):
                resolution = resolve_question_context(question, history)
                self.assertFalse(resolution.applied)

    def test_semantic_resolution_accepts_followup_without_phrase_matching(self):
        resolution = semantic_context_resolution(
            "倘若目标材料改成 SiC 会怎样",
            {
                "relation": "correction",
                "resolved_question": "比较 GaN 功率器件相对于 SiC 功率器件的优势、限制和适用场景",
                "topic_anchor": "GaN 功率器件相对于 Si 的优势",
                "confidence": 0.96,
                "intent_hint": "general_knowledge",
            },
        )

        self.assertTrue(resolution.applied)
        self.assertEqual(resolution.strategy, "semantic_correction")
        self.assertEqual(route_question(resolution.resolved_question).intent, "general_knowledge")

    def test_semantic_resolution_rejects_low_confidence_binding(self):
        resolution = semantic_context_resolution(
            "这个呢",
            {
                "relation": "followup",
                "resolved_question": "继续讨论 GaN",
                "topic_anchor": "GaN",
                "confidence": 0.4,
                "intent_hint": "unclear",
            },
        )

        self.assertFalse(resolution.applied)
        self.assertEqual(resolution.resolved_question, "这个呢")

    def test_context_window_is_bounded_and_preserves_latest_turns(self):
        history = [
            {"role": "user", "content": f"问题 {index} " + "x" * 900}
            if index % 2 == 0
            else {"role": "assistant", "content": f"回答 {index} " + "y" * 1500}
            for index in range(30)
        ]

        messages = build_contextualizer_messages(
            "继续",
            history,
            message_limit=6,
            character_budget=2500,
        )

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1], {"role": "user", "content": "继续"})
        self.assertLessEqual(sum(len(item["content"]) for item in messages[1:-1]), 2500)
        self.assertIn("回答 29", messages[-2]["content"])

    def test_agent_answers_semantic_history_recall_after_context_stage(self):
        history = [
            {"role": "user", "content": "GaN 器件相对于 Si 器件的优势"},
            {"role": "assistant", "content": "已给出基础回答。"},
        ]
        model_call = AsyncMock(return_value=_context_response(
            "recall",
            "回忆用户上一条问题",
            "GaN 器件相对于 Si 器件的优势",
        ))
        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", model_call),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "你知道我之前问的问题是啥吗",
                history,
                "run-history-recall-test",
            ))

        model_call.assert_awaited_once()
        self.assertEqual(result["intent_route"]["intent"], "conversation")
        self.assertEqual(result["context_resolution"]["strategy"], "semantic_recall")
        self.assertEqual(result["tool_trace"], [])
        self.assertIn("GaN 器件相对于 Si 器件的优势", result["answer"])

    def test_agent_semantically_resolves_unseen_followup_before_routing(self):
        history = [
            {"role": "user", "content": "GaN 器件相对于 Si 器件的优势"},
            {"role": "assistant", "content": "已给出基础回答。"},
        ]
        calls = 0

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.assertEqual(
                    request_payload["response_format"],
                    {"type": "json_object"},
                )
                self.assertNotIn("tools", request_payload)
                return _context_response(
                    "correction",
                    "比较 GaN 功率器件相对于 SiC 功率器件的优势、限制和适用场景",
                    "GaN 器件相对于 Si 器件的优势",
                )
            return ({"role": "assistant", "content": "继续比较 GaN 与 SiC。"}, {"total_tokens": 4}, "answer")

        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: []}),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "倘若目标材料换作 SiC 会是怎样",
                history,
                "run-semantic-followup-test",
            ))

        self.assertEqual(calls, 2)
        self.assertEqual(result["intent_route"]["intent"], "general_knowledge")
        self.assertTrue(result["context_resolution"]["applied"])
        self.assertEqual(result["context_resolution"]["strategy"], "semantic_correction")
        self.assertIn("SiC", result["context_resolution"]["resolved_question"])

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
        self.assertEqual(result["context_resolution"]["source"], "none")
        self.assertEqual(result["intent_route"]["intent"], "yield_decline")
        self.assertNotIn("context_resolution=", "\n".join(item["content"] for item in captured["messages"]))

    def test_context_model_protocol_failure_falls_back_without_binding_history(self):
        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            return ({"role": "assistant", "content": "无法判断"}, {}, "invalid-context")

        with patch("app.agent._stream_completion", new=invalid_stream):
            resolution, usage = asyncio.run(agent_module._resolve_conversation_turn(
                "这个怎么处理",
                [
                    {"role": "user", "content": "分析 CMP-02 报警"},
                    {"role": "assistant", "content": "已给出初步结论。"},
                ],
                _settings(),
                "run-context-fallback-test",
                None,
            ))

        self.assertFalse(resolution.applied)
        self.assertEqual(resolution.source, "fallback")
        self.assertEqual(resolution.resolved_question, "这个怎么处理")
        self.assertEqual(usage, {})

    def test_context_json_protocol_rejects_unknown_fields(self):
        assistant, _, _ = _context_response(
            "standalone",
            "介绍半导体制程",
            intent_hint="general_knowledge",
        )
        payload = json.loads(assistant["content"])
        payload["answer"] = "不应由分类器回答"
        assistant["content"] = json.dumps(payload, ensure_ascii=False)

        with self.assertRaisesRegex(ValueError, "未知字段"):
            agent_module._context_json_arguments(assistant)

    def test_context_model_retries_one_protocol_failure(self):
        calls = 0
        settings = _settings()
        settings.model_max_retries = 1

        async def flaky_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            if calls == 1:
                return ({"role": "assistant", "content": "格式错误"}, {}, "invalid-context")
            return _context_response(
                "correction",
                "当前主流的半导体制程大概有哪些",
                "当前主流的制程",
                intent_hint="general_knowledge",
            )

        with patch("app.agent._stream_completion", new=flaky_stream):
            resolution, usage = asyncio.run(agent_module._resolve_conversation_turn(
                "不涉及厂内数据",
                [
                    {"role": "user", "content": "当前主流的制程大概有哪些"},
                    {"role": "assistant", "content": "请补充生产范围。"},
                ],
                settings,
                "run-context-protocol-retry-test",
                None,
            ))

        self.assertEqual(calls, 2)
        self.assertTrue(resolution.applied)
        self.assertEqual(resolution.intent_hint, "general_knowledge")
        self.assertEqual(usage["total_tokens"], 12)

    def test_scope_only_turn_restores_unresolved_general_question(self):
        history = [
            {"role": "user", "content": "当前主流的制程大概有哪些"},
            {"role": "assistant", "content": "请补充要分析的制程站点或生产范围。"},
            {"role": "user", "content": "我说的是半导体制程"},
            {"role": "assistant", "content": "已介绍晶圆制造的主要工艺步骤。"},
        ]
        model_call = AsyncMock(return_value=_context_response(
            "followup",
            "介绍当前主流的半导体制造工艺流程，不涉及厂内数据",
            "当前主流的半导体制造工艺流程",
            confidence=0.9,
            intent_hint="general_knowledge",
        ))

        with (
            patch("app.agent._stream_completion", model_call),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: []}),
        ):
            resolution, _ = asyncio.run(agent_module._resolve_conversation_turn(
                "不涉及厂内数据",
                history,
                _settings(),
                "run-scope-only-general-test",
                None,
                route_question("不涉及厂内数据"),
            ))

        self.assertTrue(resolution.applied)
        self.assertEqual(resolution.intent_hint, "general_knowledge")
        self.assertIn("不涉及厂内数据", resolution.resolved_question)

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

    def test_unresolved_semantic_intent_still_requests_clarification(self):
        model_call = AsyncMock(return_value=_context_response(
            "standalone",
            "帮我看看这个情况",
            confidence=0.9,
            intent_hint="unclear",
        ))
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

        model_call.assert_awaited_once()
        self.assertEqual(result["mode"], "clarification")
        self.assertEqual(result["model"], "test-model")
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

    def test_unknown_first_turn_uses_semantic_general_knowledge_hint(self):
        calls = 0

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            if calls == 1:
                return _context_response(
                    "standalone",
                    "当前主流的半导体制程大概有哪些",
                    confidence=0.94,
                    intent_hint="general_knowledge",
                )
            return (
                {"role": "assistant", "content": "主流半导体制程包括光刻、刻蚀、薄膜沉积等。"},
                {"total_tokens": 5},
                "general-answer",
            )

        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: []}),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "当前主流的制程大概有哪些",
                [],
                "run-semantic-general-hint-test",
            ))

        self.assertEqual(calls, 2)
        self.assertEqual(result["intent_route"]["intent"], "general_knowledge")
        self.assertFalse(result["intent_route"]["clarification_needed"])
        self.assertEqual(result["context_resolution"]["intent_hint"], "general_knowledge")

    def test_empty_knowledge_results_fall_back_to_disclosed_model_knowledge(self):
        history = [
            {"role": "user", "content": INITIAL_QUESTION},
            {"role": "assistant", "content": CLARIFICATION},
        ]
        progress_events: list[dict] = []
        requests: list[dict] = []
        round_number = 0
        irrelevant_result = {
            "reference_id": "KB-IRRELEVANT-001",
            "source_type": "knowledge",
            "title": "设备健康与停机管理 SOP",
            "source": "Equipment_health_SOP.md",
            "section": "恢复生产",
            "excerpt": "非计划停机恢复后需要完成安全联锁检查。",
            "process_steps": "EQUIPMENT",
            "retrieval": {
                "confidence": "medium",
                "final_score": 2.2,
                "filters": {"process_step": None, "equipment_id": None, "defect_type": None},
            },
        }

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
            patch.dict(agent_module.TOOL_HANDLERS, {
                "search_knowledge": lambda **arguments: (
                    [irrelevant_result] if arguments.get("source_types") == ["personal", "knowledge"] else []
                ),
            }),
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
        self.assertIn("## 模型通用知识", result["answer"])
        self.assertNotIn("缺少字段", result["answer"])
        final_prompt = "\n".join(
            item.get("content", "")
            for item in requests[-1]["messages"]
            if item.get("role") == "system"
        )
        self.assertIn(MODEL_KNOWLEDGE_REF, final_prompt)
        self.assertTrue(any(item.get("stage") == "knowledge_fallback" for item in progress_events))


if __name__ == "__main__":
    unittest.main()
