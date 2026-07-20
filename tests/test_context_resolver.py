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
    target_message_ids: list[int] | None = None,
) -> tuple[dict, dict, str]:
    return (
        {
            "role": "assistant",
            "content": json.dumps({
                "relation": relation,
                "resolved_question": resolved_question,
                "topic_anchor": topic_anchor,
                "target_message_ids": target_message_ids or [],
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
                "target_message_ids": [],
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
                "target_message_ids": [],
                "confidence": 0.4,
                "intent_hint": "unclear",
            },
        )

        self.assertFalse(resolution.applied)
        self.assertEqual(resolution.resolved_question, "这个呢")

    def test_context_window_is_bounded_and_preserves_latest_turns(self):
        history = [
            {"message_id": index + 100, "role": "user", "content": f"问题 {index} " + "x" * 900}
            if index % 2 == 0
            else {"message_id": index + 100, "role": "assistant", "content": f"回答 {index} " + "y" * 1500}
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
        self.assertIn("[message_id=129]", messages[-2]["content"])

    def test_agent_answers_semantic_history_recall_after_context_stage(self):
        model_call = AsyncMock(return_value=_context_response(
            "recall",
            "回忆用户上一条问题",
            "GaN 器件相对于 Si 器件的优势",
            target_message_ids=[11],
        ))
        history = [
            {"message_id": 11, "role": "user", "content": "GaN 器件相对于 Si 器件的优势"},
            {"message_id": 12, "role": "assistant", "content": "已给出基础回答。"},
        ]
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
        self.assertEqual(result["context_resolution"]["target_message_ids"], [11])
        self.assertNotIn("recalled_messages", result["context_resolution"])
        self.assertIn("助手消息 #12", result["answer"])

    def test_recall_uses_original_run_scope_instead_of_generated_topic_anchor(self):
        history = [
            {"message_id": 21, "role": "user", "content": "分析一下最近 PH 的生产状况"},
            {
                "message_id": 22,
                "role": "assistant",
                "content": "已完成生产分析。",
                "metadata": {
                    "intent_route": {
                        "intent": "fab_diagnostic",
                        "process_steps": [],
                        "scope_resolution": {
                            "scope_type": "fab",
                            "resolved_ids": [],
                        },
                    },
                },
            },
        ]
        model_call = AsyncMock(return_value=_context_response(
            "recall",
            "说明上一轮实际如何理解 PH",
            "PH 光刻",
            target_message_ids=[21],
        ))

        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", model_call),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "你在上一个问题中理解的 PH 是什么",
                history,
                "run-history-scope-audit-test",
            ))

        self.assertIn("没有解析出具体制程或设备范围", result["answer"])
        self.assertIn("整厂综合诊断", result["answer"])
        self.assertNotIn("PH 光刻", result["answer"])

    def test_recall_reports_unknown_scope_as_blocked_instead_of_fab_wide(self):
        history = [
            {"message_id": 25, "role": "user", "content": "分析一下最近 PH 的生产状况"},
            {
                "message_id": 26,
                "role": "assistant",
                "content": "请确认 PH 的含义。",
                "metadata": {
                    "intent_route": {
                        "intent": "fab_diagnostic",
                        "process_steps": [],
                        "scope_resolution": {
                            "scope_type": "unknown",
                            "resolved_ids": [],
                            "unresolved_mentions": ["PH"],
                        },
                    },
                    "tool_trace": [],
                },
            },
        ]
        model_call = AsyncMock(return_value=_context_response(
            "recall",
            "说明更早一轮如何理解 PH",
            "PH 光刻",
            target_message_ids=[25],
        ))

        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", model_call),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "是更前面的一个",
                history,
                "run-history-unknown-scope-audit-test",
            ))

        self.assertIn("制造范围记录为未知（PH）", result["answer"])
        self.assertIn("实际执行了 0 个工具", result["answer"])
        self.assertNotIn("整厂综合诊断执行", result["answer"])
        self.assertNotIn("PH 光刻", result["answer"])

    def test_recall_can_select_an_older_message_by_id(self):
        history = [
            {"message_id": 31, "role": "user", "content": "最早的问题"},
            {"message_id": 32, "role": "assistant", "content": "最早的回答"},
            {"message_id": 33, "role": "user", "content": "后一个问题"},
            {"message_id": 34, "role": "assistant", "content": "后一个回答"},
        ]
        resolution = semantic_context_resolution(
            "是更前面的一个",
            {
                "relation": "recall",
                "resolved_question": "回忆更早的问题",
                "topic_anchor": "模型生成的锚点",
                "target_message_ids": [31],
                "confidence": 0.96,
                "intent_hint": "unclear",
            },
            history,
        )

        self.assertTrue(resolution.applied)
        self.assertEqual(resolution.target_message_ids, (31,))
        self.assertEqual(
            [item["message_id"] for item in resolution.recalled_messages],
            [31, 32],
        )
        self.assertIn("最早的问题", resolution.selected_context)
        self.assertNotIn("模型生成的锚点", resolution.selected_context)

    def test_recall_rejects_message_ids_outside_supplied_history(self):
        resolution = semantic_context_resolution(
            "回忆之前的问题",
            {
                "relation": "recall",
                "resolved_question": "回忆之前的问题",
                "topic_anchor": "",
                "target_message_ids": [999],
                "confidence": 0.95,
                "intent_hint": "unclear",
            },
            [{"message_id": 1, "role": "user", "content": "真实历史问题"}],
        )

        self.assertFalse(resolution.applied)
        self.assertEqual(resolution.source, "fallback")

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
        calls = 0
        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            if calls == 1:
                return _context_response(
                    "correction",
                    "分析最近四周良率",
                    INITIAL_QUESTION,
                    intent_hint="manufacturing_analysis",
                )
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

        self.assertEqual(calls, 2)
        self.assertTrue(result["context_resolution"]["applied"])
        self.assertEqual(result["context_resolution"]["source"], "model")
        self.assertEqual(result["intent_route"]["intent"], "yield_decline")
        self.assertIn("context_resolution=", "\n".join(item["content"] for item in captured["messages"]))

    def test_agent_model_resolves_personal_knowledge_preference_as_general_followup(self):
        history = [
            {"role": "user", "content": "为我简单介绍一下光刻"},
            {"role": "assistant", "content": "知识库没有检索到可用内容，以下使用模型通用知识介绍光刻。"},
        ]
        calls = 0

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            if calls == 1:
                return _context_response(
                    "correction",
                    "优先检索我的个人知识库，并继续介绍光刻的基本原理和工艺流程",
                    "介绍光刻",
                    confidence=0.94,
                    intent_hint="general_knowledge",
                )
            return (
                {"role": "assistant", "content": "已根据个人知识继续介绍光刻。"},
                {"total_tokens": 5},
                "personal-knowledge-answer",
            )

        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: []}),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "我知识库里有相关知识啊",
                history,
                "run-personal-knowledge-followup-test",
            ))

        self.assertEqual(calls, 2)
        self.assertEqual(result["context_resolution"]["strategy"], "semantic_correction")
        self.assertIn("继续介绍光刻", result["context_resolution"]["resolved_question"])
        self.assertEqual(result["intent_route"]["intent"], "general_knowledge")
        self.assertIsNone(result["domain_playbook"]["selected_playbook"])

    def test_context_model_protocol_failure_falls_back_without_binding_history(self):
        calls = 0

        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            return ({"role": "assistant", "content": "无法判断"}, {}, "invalid-context")

        with patch("app.agent._stream_completion", new=invalid_stream):
            resolution, usage = asyncio.run(agent_module._resolve_conversation_turn(
                "是更前面的一个",
                [
                    {"role": "user", "content": "分析 CMP-02 报警"},
                    {"role": "assistant", "content": "已给出初步结论。"},
                ],
                _settings(),
                "run-context-fallback-test",
                None,
            ))

        self.assertEqual(calls, 2)
        self.assertFalse(resolution.applied)
        self.assertEqual(resolution.source, "fallback")
        self.assertEqual(resolution.strategy, "context_clarification")
        self.assertEqual(resolution.resolved_question, "是更前面的一个")
        self.assertEqual(resolution.failure_reason, "invalid_json")
        self.assertEqual(usage, {})

    def test_context_json_protocol_ignores_unknown_fields(self):
        assistant, _, _ = _context_response(
            "standalone",
            "介绍半导体制程",
            intent_hint="general_knowledge",
        )
        payload = json.loads(assistant["content"])
        payload["answer"] = "不应由分类器回答"
        assistant["content"] = json.dumps(payload, ensure_ascii=False)

        arguments = agent_module._context_json_arguments(assistant)

        self.assertEqual(arguments["relation"], "standalone")
        self.assertEqual(arguments["answer"], "不应由分类器回答")

    def test_context_json_protocol_accepts_json_code_fence(self):
        assistant, _, _ = _context_response(
            "standalone",
            "介绍半导体制程",
            intent_hint="general_knowledge",
        )
        assistant["content"] = f"```json\n{assistant['content']}\n```"

        arguments = agent_module._context_json_arguments(assistant)

        self.assertEqual(arguments["intent_hint"], "general_knowledge")

    def test_context_json_protocol_rejects_invalid_field_types_with_reason(self):
        assistant, _, _ = _context_response("standalone", "介绍半导体制程")
        payload = json.loads(assistant["content"])
        payload["target_message_ids"] = [True]
        assistant["content"] = json.dumps(payload, ensure_ascii=False)

        with self.assertRaises(agent_module.ContextProtocolError) as captured:
            agent_module._context_json_arguments(assistant)

        self.assertEqual(captured.exception.code, "invalid_field_type")
        self.assertEqual(captured.exception.response_length, len(assistant["content"]))
        self.assertTrue(captured.exception.response_fingerprint)

    def test_context_model_retries_one_protocol_failure(self):
        calls = 0
        settings = _settings()
        settings.model_max_retries = 1

        async def flaky_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            if calls == 1:
                return ({"role": "assistant", "content": "格式错误"}, {}, "invalid-context")
            self.assertIn("invalid_json", request_payload["messages"][-1]["content"])
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

    def test_empty_context_response_expands_only_retry_token_budget(self):
        calls = 0

        async def empty_then_valid(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.assertEqual(request_payload["max_tokens"], 1200)
                stream_state["reasoning_length"] = 1100
                stream_state["finish_reason"] = "length"
                return ({"role": "assistant", "content": ""}, {}, "empty-context")
            self.assertEqual(request_payload["max_tokens"], 2400)
            return _context_response(
                "recall",
                "回忆上一条问题",
                target_message_ids=[81],
            )

        with patch("app.agent._stream_completion", new=empty_then_valid):
            resolution, usage = asyncio.run(agent_module._resolve_conversation_turn(
                "你在上一个问题中理解的主题是什么",
                [
                    {"message_id": 81, "role": "user", "content": "介绍光刻基本原理"},
                    {"message_id": 82, "role": "assistant", "content": "已完成介绍。"},
                ],
                _settings(),
                "run-context-empty-budget-test",
                None,
            ))

        self.assertEqual(calls, 2)
        self.assertEqual(resolution.strategy, "semantic_recall")
        self.assertEqual(resolution.target_message_ids, (81,))
        self.assertEqual(usage["total_tokens"], 12)

    def test_repeated_empty_context_response_blocks_general_knowledge_fallback(self):
        question = "你在上一个问题中理解的主题是什么"

        async def empty_stream(client, endpoint, headers, request_payload, progress, stream_state):
            stream_state["reasoning_length"] = int(request_payload["max_tokens"])
            stream_state["finish_reason"] = "length"
            return ({"role": "assistant", "content": ""}, {}, "empty-context")

        direct_route = route_question(question)
        self.assertEqual(direct_route.intent, "general_knowledge")
        with patch("app.agent._stream_completion", new=empty_stream):
            resolution, _ = asyncio.run(agent_module._resolve_conversation_turn(
                question,
                [
                    {"message_id": 91, "role": "user", "content": "介绍光刻基本原理"},
                    {"message_id": 92, "role": "assistant", "content": "已完成介绍。"},
                ],
                _settings(),
                "run-context-empty-general-fallback-test",
                None,
                direct_route,
            ))

        self.assertEqual(resolution.strategy, "context_clarification")
        self.assertEqual(resolution.failure_reason, "empty_response")

    def test_context_protocol_failure_retries_only_once_even_with_larger_model_budget(self):
        calls = 0
        settings = _settings()
        settings.model_max_retries = 4

        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            return ({"role": "assistant", "content": "仍然不是 JSON"}, {}, "invalid-context")

        with patch("app.agent._stream_completion", new=invalid_stream):
            resolution, _ = asyncio.run(agent_module._resolve_conversation_turn(
                "是更前面的一个",
                [
                    {"message_id": 41, "role": "user", "content": "分析 CMP-02 报警"},
                    {"message_id": 42, "role": "assistant", "content": "已给出初步结论。"},
                ],
                settings,
                "run-context-protocol-budget-test",
                None,
            ))

        self.assertEqual(calls, 2)
        self.assertEqual(resolution.strategy, "context_clarification")

    def test_context_protocol_metadata_logs_reason_without_response_content(self):
        events: list[tuple[str, dict]] = []

        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            return ({"role": "assistant", "content": "不合法的完整响应"}, {}, "invalid-context")

        def capture(event_type: str, run_id: str, **fields) -> None:
            events.append((event_type, fields))

        with (
            patch("app.agent._stream_completion", new=invalid_stream),
            patch("app.agent.emit", new=capture),
            patch("app.agent.CONTENT_MODE", "metadata"),
        ):
            asyncio.run(agent_module._resolve_conversation_turn(
                "是更前面的一个",
                [{"message_id": 61, "role": "user", "content": "此前的问题"}],
                _settings(),
                "run-context-protocol-log-test",
                None,
            ))

        failures = [fields for event, fields in events if event == "model_call_finished"]
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(item["protocol_error_code"] == "invalid_json" for item in failures))
        self.assertTrue(all(item["response_length"] == len("不合法的完整响应") for item in failures))
        self.assertTrue(all(item["response_fingerprint"] for item in failures))
        self.assertTrue(all("response" not in item for item in failures))

    def test_context_protocol_failure_preserves_independent_manufacturing_route(self):
        question = "分析最近一周刻蚀机台状况"

        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            return ({"role": "assistant", "content": "格式错误"}, {}, "invalid-context")

        direct_route = route_question(question)
        with patch("app.agent._stream_completion", new=invalid_stream):
            resolution, _ = asyncio.run(agent_module._resolve_conversation_turn(
                question,
                [
                    {"message_id": 71, "role": "user", "content": "介绍 GaN"},
                    {"message_id": 72, "role": "assistant", "content": "已完成介绍。"},
                ],
                _settings(),
                "run-context-independent-manufacturing-test",
                None,
                direct_route,
            ))

        self.assertEqual(resolution.strategy, "none")
        self.assertEqual(resolution.resolved_question, question)
        self.assertEqual(direct_route.intent, "fab_diagnostic")
        self.assertEqual(direct_route.process_steps, ("ETCH",))

    def test_agent_context_failure_lists_recent_user_messages_instead_of_manufacturing_prompt(self):
        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            return ({"role": "assistant", "content": "无法输出结构化结果"}, {}, "invalid-context")

        history = [
            {"message_id": 51, "role": "user", "content": "GaN 相对于 Si 的优势"},
            {"message_id": 52, "role": "assistant", "content": "已完成材料比较。"},
            {"message_id": 53, "role": "user", "content": "那么 SiC 呢"},
            {"message_id": 54, "role": "assistant", "content": "已完成 SiC 比较。"},
        ]
        with (
            patch("app.agent.get_settings", return_value=_settings()),
            patch("app.agent._stream_completion", new=invalid_stream),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "是更前面的一个",
                history,
                "run-context-specific-clarification-test",
            ))

        self.assertEqual(result["intent_route"]["intent"], "conversation")
        self.assertEqual(result["context_resolution"]["strategy"], "context_clarification")
        self.assertEqual(result["tool_trace"], [])
        self.assertIn("消息 #53", result["answer"])
        self.assertIn("消息 #51", result["answer"])
        self.assertNotIn("制程站点", result["answer"])
        self.assertNotIn("设备编号", result["answer"])

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
