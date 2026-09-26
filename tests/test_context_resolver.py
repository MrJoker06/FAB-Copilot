from __future__ import annotations

import asyncio
import json
import time
import unittest
import httpx
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent_runtime import service as agent_module
from app.evidence.answer_synthesizer import MODEL_KNOWLEDGE_REF
from app.conversation.context_resolver import (
    build_contextualizer_messages,
    resolve_question_context,
    semantic_context_resolution,
)
from app.intent_runtime.routing import route_question


INITIAL_QUESTION = "GaN器件和纯Si器件的差异"
CLARIFICATION = """为了继续，请选择分析方向：
- 比较制造指标，例如 Cpk 或良率
- 指定工艺站点或设备
- 指定时间范围
- 结合历史案例或 SOP 规范
- 先展示两类器件在晶圆厂内的基本工艺路线差异（需要调用知识库）"""


def _settings():
    return SimpleNamespace(
        model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
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
    turn_actions: list[dict] | None = None,
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
                **({"turn_actions": turn_actions} if turn_actions is not None else {}),
            }, ensure_ascii=False),
        },
        {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
        "context-response",
    )


class ContextResolverTests(unittest.TestCase):
    def test_trace_records_safe_arbitration_candidates_and_separate_versions(self):
        events: list[tuple[str, dict]] = []

        def capture(event_type: str, _run_id: str, **fields) -> None:
            events.append((event_type, fields))

        with patch("app.agent_runtime.service.get_settings", return_value=_settings()), patch("app.agent_runtime.service.emit", new=capture):
            asyncio.run(agent_module._run_agent_impl("你有什么功能", [], "trace-arbitration"))

        decision = next(fields for event, fields in events if event == "turn_decision_created")
        self.assertNotIn("schema_version", decision)
        self.assertEqual(decision["turn_decision_schema_version"], "1.0")
        self.assertEqual(
            decision["decision_candidate_count"],
            decision["selected_candidate_count"] + decision["rejected_candidate_count"],
        )
        self.assertEqual({item["status"] for item in decision["decision_candidates"]}, {"selected", "rejected"})
        self.assertTrue(all(set(item) == {"kind", "value", "origin", "confidence", "status", "reason"} for item in decision["decision_candidates"]))
        self.assertTrue(any(event == "context_stage_completed" for event, _ in events))
        self.assertTrue(any(event == "routing_stage_completed" for event, _ in events))

    def test_real_router_failure_replay_stays_in_capability_flow_without_tools(self):
        async def contextualizer(*_args):
            return _context_response(
                "followup",
                "请具体说明 Fab Copilot 的功能，包括个人文档管理与检索能力",
                "助手能力",
                .95,
                "conversation",
                turn_actions=[{"type": "answer_meta", "subject": "capabilities", "detail": "detailed"}],
            )
        history: list[dict] = []
        with patch("app.agent_runtime.service.get_settings", return_value=_settings()), patch("app.agent_runtime.service._stream_completion", new=contextualizer):
            identity = asyncio.run(agent_module._run_agent_impl("介绍一下你自己", history, "arbiter-identity"))
            history += [{"role": "user", "content": "介绍一下你自己"}, {"role": "assistant", "content": identity["answer"], "metadata": identity}]
            capabilities = asyncio.run(agent_module._run_agent_impl("你有什么功能", history, "arbiter-capabilities"))
            history += [{"role": "user", "content": "你有什么功能"}, {"role": "assistant", "content": capabilities["answer"], "metadata": capabilities}]
            result = asyncio.run(agent_module._run_agent_impl("具体一点", history, "arbiter-detail"))
        self.assertEqual(result["intent_route"]["intent"], "conversation")
        self.assertEqual(result["turn_decision"]["actions"][0]["type"], "answer_meta")
        self.assertEqual(result["turn_decision"]["actions"][0]["subject"], "capabilities")
        self.assertEqual(result["turn_decision"]["actions"][0]["detail"], "detailed")
        self.assertEqual(result["turn_decision"]["active_flow"], "meta:capabilities")
        self.assertEqual(result["turn_decision"]["selected_origin"], "semantic_context")
        self.assertEqual(result["turn_decision"]["policy_reason"], "active_meta_flow_continuation")
        self.assertEqual(result["tool_trace"], [])
        self.assertEqual(result["retrieval_decision"]["state"], "NOT_APPLICABLE")

    def test_explicit_task_pipeline_uses_original_question_after_bad_expansion(self):
        context = semantic_context_resolution(
            "分析昨天良率，但优先参考知识库",
            {
                "relation": "correction",
                "resolved_question": "优先使用知识库中的文档",
                "topic_anchor": "良率",
                "target_message_ids": [],
                "confidence": .95,
                "intent_hint": "general_knowledge",
            },
        )
        captured: dict[str, str] = {}
        original_create_plan = agent_module.create_execution_plan

        async def resolved_context(*_args, **_kwargs):
            return context, {}

        def capture_plan(question, *args, **kwargs):
            captured["question"] = question
            return original_create_plan(question, *args, **kwargs)

        settings = _settings()
        settings.model_connection.api_key = ""
        with (
            patch("app.agent_runtime.service.get_settings", return_value=settings),
            patch("app.agent_runtime.service._resolve_conversation_turn", new=resolved_context),
            patch("app.agent_runtime.service.create_execution_plan", new=capture_plan),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "分析昨天良率，但优先参考知识库",
                [{"role": "assistant", "content": "上轮回答", "metadata": {}}],
                "arbiter-original-question",
            ))
        self.assertEqual(result["intent_route"]["intent"], "yield_decline")
        self.assertEqual(captured["question"], "分析昨天良率，但优先参考知识库")
        self.assertNotIn("优先使用知识库中的文档", captured["question"])

    def test_four_turn_capability_conversation_uses_distinct_deterministic_answers(self):
        calls = 0
        async def contextualizer(*_args):
            nonlocal calls
            calls += 1
            return _context_response("correction" if calls == 2 else "followup", "Fab Copilot 具体有哪些功能", "助手能力", .95, "conversation", turn_actions=[{"type":"answer_meta","subject":"capabilities","detail":"detailed"}])
        settings = _settings()
        history = []
        with patch("app.agent_runtime.service.get_settings", return_value=settings), patch("app.agent_runtime.service._stream_completion", new=contextualizer) as model:
            one = asyncio.run(agent_module._run_agent_impl("你是谁", history, "four-1")); history += [{"role":"user","content":"你是谁"}, {"role":"assistant","content":one["answer"],"metadata":one}]
            two = asyncio.run(agent_module._run_agent_impl("你有什么功能", history, "four-2")); history += [{"role":"user","content":"你有什么功能"}, {"role":"assistant","content":two["answer"],"metadata":two}]
            three = asyncio.run(agent_module._run_agent_impl("具体的功能有哪些", history, "four-3")); history += [{"role":"user","content":"具体的功能有哪些"}, {"role":"assistant","content":three["answer"],"metadata":three}]
            four = asyncio.run(agent_module._run_agent_impl("我说的是你具备哪些具体的能力而不是宽泛的说明", history, "four-4"))
        self.assertEqual(len({one["answer"], two["answer"], three["answer"], four["answer"]}), 4, (one["answer"], two["answer"], three["answer"], four["answer"]))
        self.assertEqual(four["context_resolution"]["strategy"], "semantic_correction")
        self.assertIn("例如：", four["answer"]); self.assertIn("限制：", four["answer"])
        for result in (one, two, three, four):
            self.assertEqual(result["tool_trace"], [])
            self.assertEqual(result["retrieval_decision"]["state"], "NOT_APPLICABLE")
        self.assertEqual(calls, 2)
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

    def test_ordinal_selection_binds_most_recent_clarification(self):
        # 已知语义歧义：当会话中存在多次带列表的澄清时，确定性解析
        # 无条件绑定最近一次，且 confidence=1.0。用户可能指的是更早的
        # 一次澄清，但纯规则无法区分。此测试锁定现状，便于后续讨论修复。
        resolution = resolve_question_context(
            "选第2点",
            [
                {"role": "user", "content": "分析最近良率"},
                {"role": "assistant", "content": "第一次澄清，请选择：\n- 比较 Cpk\n- 指定设备\n- 指定时间范围"},
                {"role": "user", "content": "先帮我看看设备告警"},
                {"role": "assistant", "content": "第二次澄清，请选择：\n- 看异常批次\n- 看设备健康"},
            ],
        )

        self.assertTrue(resolution.applied)
        self.assertEqual(resolution.strategy, "ordinal_selection")
        self.assertEqual(resolution.selected_context, "看设备健康")
        self.assertEqual(resolution.confidence, 1.0)
        self.assertEqual(resolution.source, "deterministic")
        self.assertEqual(resolution.relation, "followup")
        self.assertIn("先帮我看看设备告警", resolution.resolved_question)

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
        self.assertEqual(resolution.resolution_state, "ambiguous")
        self.assertEqual(resolution.strategy, "context_clarification")

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
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", model_call),
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
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", model_call),
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
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", model_call),
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
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", new=fake_stream),
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
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", new=fake_stream),
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
        synthesis_task = json.loads(captured["messages"][-1]["content"])
        self.assertEqual(synthesis_task["question"], "最后一点先放下，改为分析最近四周良率")
        self.assertEqual(synthesis_task["intent"], "yield_decline")

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
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", new=fake_stream),
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

        with patch("app.agent_runtime.service._stream_completion", new=invalid_stream):
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
        self.assertEqual(resolution.strategy, "none")
        self.assertEqual(resolution.resolution_state, "unavailable")
        self.assertEqual(resolution.resolved_question, "是更前面的一个")
        self.assertEqual(resolution.failure_reason, "invalid_json")
        self.assertEqual(usage, {})

    def test_run_audits_context_unavailable_as_degraded_success(self):
        events: list[tuple[str, dict]] = []

        async def degraded_impl(*_args, **_kwargs):
            return {
                "answer": "请把问题写完整一些。",
                "mode": "clarification",
                "tool_trace": [],
                "sources": [],
                "intent_route": {},
                "context_resolution": {
                    "resolution_state": "unavailable",
                    "failure_reason": "timeout",
                },
            }

        def capture(event_type: str, run_id: str, **fields) -> None:
            events.append((event_type, fields))

        with patch("app.agent_runtime.service._run_agent_impl", new=degraded_impl), patch("app.agent_runtime.service.emit", new=capture):
            result = asyncio.run(agent_module.run_agent(
                "你有什么功能", [{"role": "user", "content": "你是谁"}],
                session_id="session-a", user_message_id=42,
            ))

        self.assertEqual(result["status"], "success")
        finished = next(fields for event, fields in events if event == "agent_run_finished")
        self.assertEqual(finished["status"], "success")
        self.assertEqual(finished["outcome"], "degraded")
        self.assertTrue(finished["degraded"])
        self.assertEqual(finished["degradation_reason"], "timeout")
        self.assertEqual(finished["session_id"], "session-a")
        self.assertEqual(finished["user_message_id"], 42)
        started = next(fields for event, fields in events if event == "agent_run_started")
        self.assertEqual((started["session_id"], started["user_message_id"]), ("session-a", 42))

    def test_deepseek_contextualizer_disables_thinking_but_audits_request(self):
        captured = []
        events: list[tuple[str, dict]] = []

        def capture(event_type: str, run_id: str, **fields) -> None:
            events.append((event_type, fields))

        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            captured.append(request_payload.copy())
            return ({"role": "assistant", "content": "not json"}, {}, "context")
        settings = _settings()
        settings.model_connection = SimpleNamespace(provider="deepseek", api_key="test-key", base_url="https://example.test", model="test-model")
        history = [{"role": "user", "content": "分析 CMP-02 报警"}, {"role": "assistant", "content": "已给出初步结论。"}]
        with patch("app.agent_runtime.service._stream_completion", new=invalid_stream), patch("app.agent_runtime.service.emit", new=capture):
            asyncio.run(agent_module._resolve_conversation_turn("是更前面的一个", history, settings, "run-context-deepseek-false", None))
        self.assertTrue(all(item["thinking"] == {"type": "disabled"} for item in captured))
        captured.clear()
        events.clear()
        with patch("app.agent_runtime.service._stream_completion", new=invalid_stream), patch("app.agent_runtime.service.emit", new=capture):
            asyncio.run(agent_module._resolve_conversation_turn("是更前面的一个", history, settings, "run-context-deepseek-true", None, thinking=True))
        self.assertTrue(all(item["thinking"] == {"type": "disabled"} for item in captured))
        calls = [fields for event, fields in events if event == "model_call_started"]
        self.assertTrue(calls)
        self.assertTrue(all(item["thinking_requested"] for item in calls))
        self.assertTrue(all(not item["thinking_effective"] for item in calls))

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

        with patch("app.agent_runtime.service._stream_completion", new=flaky_stream):
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
        events: list[tuple[str, dict]] = []

        def capture(event_type: str, run_id: str, **fields) -> None:
            events.append((event_type, fields))

        async def empty_then_valid(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            if calls == 1:
                self.assertEqual(request_payload["max_tokens"], 1200)
                stream_state["reasoning_length"] = 1100
                stream_state["finish_reason"] = "length"
                return ({"role": "assistant", "content": ""}, {}, "empty-context")
            self.assertEqual(request_payload["max_tokens"], 2400)
            stream_state["reasoning_length"] = 450
            stream_state["finish_reason"] = "stop"
            return _context_response(
                "recall",
                "回忆上一条问题",
                target_message_ids=[81],
            )

        with (
            patch("app.agent_runtime.service._stream_completion", new=empty_then_valid),
            patch("app.agent_runtime.service.emit", new=capture),
        ):
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
        successes = [
            fields
            for event, fields in events
            if event == "model_call_finished" and fields.get("status") == "success"
        ]
        self.assertEqual(successes[0]["reasoning_length"], 450)
        self.assertEqual(successes[0]["finish_reason"], "stop")

    def test_repeated_empty_context_response_blocks_general_knowledge_fallback(self):
        question = "你在上一个问题中理解的主题是什么"

        async def empty_stream(client, endpoint, headers, request_payload, progress, stream_state):
            stream_state["reasoning_length"] = int(request_payload["max_tokens"])
            stream_state["finish_reason"] = "length"
            return ({"role": "assistant", "content": ""}, {}, "empty-context")

        direct_route = route_question(question)
        self.assertEqual(direct_route.intent, "general_knowledge")
        with patch("app.agent_runtime.service._stream_completion", new=empty_stream):
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

        self.assertEqual(resolution.strategy, "none")
        self.assertEqual(resolution.resolution_state, "unavailable")
        self.assertEqual(resolution.failure_reason, "context_budget_exhausted")

    def test_context_budget_exhaustion_audits_normalized_reason_and_never_records_reasoning(self):
        events: list[tuple[str, dict]] = []

        async def empty_stream(client, endpoint, headers, request_payload, progress, stream_state):
            stream_state["reasoning_length"] = int(request_payload["max_tokens"])
            stream_state["finish_reason"] = "length"
            return ({"role": "assistant", "content": "", "reasoning_content": "private"}, {}, "empty-context")

        def capture(event_type: str, run_id: str, **fields) -> None:
            events.append((event_type, fields))

        with patch("app.agent_runtime.service._stream_completion", new=empty_stream), patch("app.agent_runtime.service.emit", new=capture):
            resolution, _ = asyncio.run(agent_module._resolve_conversation_turn(
                "你在上一个问题中理解的主题是什么",
                [{"message_id": 91, "role": "user", "content": "介绍光刻基本原理"}],
                _settings(), "run-context-budget-audit-test", None,
            ))

        self.assertEqual(resolution.failure_reason, "context_budget_exhausted")
        failures = [fields for event, fields in events if event == "model_call_finished"]
        self.assertEqual([item["failure_reason"] for item in failures], ["context_budget_exhausted", "context_budget_exhausted"])
        self.assertEqual([item["reasoning_length"] for item in failures], [1200, 2400])
        self.assertTrue(all("reasoning_content" not in item for item in failures))

    def test_context_deadline_stops_transport_retries_and_falls_back(self):
        calls = 0
        events: list[tuple[str, dict]] = []
        settings = _settings()
        settings.model_max_retries = 4
        settings.model_context_timeout_seconds = 0.05
        settings.model_circuit_failure_threshold = 3
        settings.model_circuit_cooldown_seconds = 60

        async def timeout_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("simulated")

        def capture(event_type: str, run_id: str, **fields) -> None:
            events.append((event_type, fields))

        ticks = iter((0.0, 0.001, 0.002, 0.003, 0.004, 0.005, 0.06))
        with (
            patch("app.agent_runtime.service._stream_completion", new=timeout_stream),
            patch("app.agent_runtime.service._model_retry_delay", return_value=0.01),
            patch("app.agent_runtime.service.asyncio.sleep", new=AsyncMock()),
            patch("app.agent_runtime.service.time.perf_counter", side_effect=lambda: next(ticks)),
            patch("app.agent_runtime.service.emit", new=capture),
            patch("app.agent_runtime.service.record_model_failure", return_value=({"status": "degraded"}, None)) as record_failure,
        ):
            resolution, usage = asyncio.run(agent_module._resolve_conversation_turn(
                "是更前面的一个",
                [{"message_id": 91, "role": "user", "content": "介绍光刻基本原理"}],
                settings, "run-context-deadline-test", None, health_model_id="context-model",
            ))

        self.assertEqual(calls, 1)
        self.assertEqual(usage, {})
        self.assertEqual(resolution.strategy, "none")
        self.assertEqual(resolution.resolution_state, "unavailable")
        self.assertEqual(sum(event == "model_call_started" for event, _ in events), 1)
        failures = [fields for event, fields in events if event == "question_context_resolution_failed"]
        self.assertEqual(failures[-1]["failure_reason"], "timeout")
        record_failure.assert_called_once()
        self.assertEqual(record_failure.call_args.args[:2], ("context-model", "timeout"))

    def test_context_deadline_does_not_sleep_when_backoff_exceeds_remaining_budget(self):
        calls = 0
        settings = _settings()
        settings.model_max_retries = 4
        settings.model_retry_base_seconds = 1.0
        settings.model_context_timeout_seconds = 0.05

        async def timeout_stream(*args):
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("simulated")

        sleep = AsyncMock()
        with (
            patch("app.agent_runtime.service._stream_completion", new=timeout_stream),
            patch("app.agent_runtime.service.asyncio.sleep", new=sleep),
            patch("app.agent_runtime.service.time.perf_counter", return_value=0.0),
        ):
            resolution, _ = asyncio.run(agent_module._resolve_conversation_turn(
                "是更前面的一个",
                [{"message_id": 91, "role": "user", "content": "介绍光刻基本原理"}],
                settings, "run-context-backoff-deadline-test", None,
            ))

        self.assertEqual(calls, 1)
        sleep.assert_not_awaited()
        self.assertEqual(resolution.strategy, "none")
        self.assertEqual(resolution.resolution_state, "unavailable")

    def test_context_deadline_cancels_slow_request_and_falls_back(self):
        calls = 0
        cancelled_after: float | None = None
        settings = _settings()
        settings.model_context_timeout_seconds = 0.05

        async def slow_stream(*args):
            nonlocal calls, cancelled_after
            calls += 1
            started = time.monotonic()
            try:
                await asyncio.sleep(0.2)
                return _context_response("standalone", "ignored")
            except asyncio.CancelledError:
                cancelled_after = time.monotonic() - started
                raise

        with (
            patch("app.agent_runtime.service._stream_completion", new=slow_stream),
            patch("app.agent_runtime.service.time.perf_counter", return_value=0.0),
        ):
            resolution, _ = asyncio.run(agent_module._resolve_conversation_turn(
                "是更前面的一个",
                [{"message_id": 91, "role": "user", "content": "介绍光刻基本原理"}],
                settings, "run-context-async-deadline-test", None,
            ))

        self.assertEqual(calls, 1)
        self.assertIsNotNone(cancelled_after)
        self.assertLess(cancelled_after, 0.15)
        self.assertEqual(resolution.strategy, "none")
        self.assertEqual(resolution.resolution_state, "unavailable")

    def test_non_retryable_context_error_is_not_audited_as_network(self):
        events: list[tuple[str, dict]] = []

        async def invalid_stream(*args):
            raise ValueError("local parser failed")

        def capture(event_type: str, run_id: str, **fields) -> None:
            events.append((event_type, fields))

        with patch("app.agent_runtime.service._stream_completion", new=invalid_stream), patch("app.agent_runtime.service.emit", new=capture):
            asyncio.run(agent_module._resolve_conversation_turn(
                "是更前面的一个",
                [{"message_id": 91, "role": "user", "content": "介绍光刻基本原理"}],
                _settings(), "run-context-local-error-test", None,
            ))

        failure = next(fields for event, fields in events if event == "model_call_finished")
        self.assertEqual(failure["failure_reason"], "protocol_error")

    def test_thinking_policy_marks_answer_effective_only_after_main_model_success(self):
        async def successful_stream(*args):
            return ({"role": "assistant", "content": "模型回答"}, {"total_tokens": 1}, "answer")

        with patch("app.agent_runtime.service.get_settings", return_value=_settings()), patch("app.agent_runtime.service._stream_completion", new=successful_stream):
            result = asyncio.run(agent_module._run_agent_impl(
                "介绍半导体制程", [], "run-thinking-answer-success", thinking=True,
            ))
        self.assertTrue(result["thinking_policy"]["requested"])
        self.assertTrue(result["thinking_policy"]["answer_effective"])

        async def context_only_stream(*args):
            return _context_response("standalone", "帮我看看这个情况", confidence=0.9, intent_hint="unclear")

        with patch("app.agent_runtime.service.get_settings", return_value=_settings()), patch("app.agent_runtime.service._stream_completion", new=context_only_stream):
            clarification = asyncio.run(agent_module.run_agent(
                "帮我看看这个情况", [], thinking=True,
            ))
        self.assertTrue(clarification["thinking_policy"]["requested"])
        self.assertFalse(clarification["thinking_policy"]["answer_effective"])

    def test_context_protocol_failure_retries_only_once_even_with_larger_model_budget(self):
        calls = 0
        settings = _settings()
        settings.model_max_retries = 4

        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal calls
            calls += 1
            return ({"role": "assistant", "content": "仍然不是 JSON"}, {}, "invalid-context")

        with patch("app.agent_runtime.service._stream_completion", new=invalid_stream):
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
        self.assertEqual(resolution.strategy, "none")
        self.assertEqual(resolution.resolution_state, "unavailable")

    def test_context_protocol_metadata_logs_reason_without_response_content(self):
        events: list[tuple[str, dict]] = []

        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            return ({"role": "assistant", "content": "不合法的完整响应"}, {}, "invalid-context")

        def capture(event_type: str, run_id: str, **fields) -> None:
            events.append((event_type, fields))

        with (
            patch("app.agent_runtime.service._stream_completion", new=invalid_stream),
            patch("app.agent_runtime.service.emit", new=capture),
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
        with patch("app.agent_runtime.service._stream_completion", new=invalid_stream):
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

    def test_agent_context_failure_keeps_current_question_and_uses_neutral_clarification(self):
        async def invalid_stream(client, endpoint, headers, request_payload, progress, stream_state):
            return ({"role": "assistant", "content": "无法输出结构化结果"}, {}, "invalid-context")

        history = [
            {"message_id": 51, "role": "user", "content": "GaN 相对于 Si 的优势"},
            {"message_id": 52, "role": "assistant", "content": "已完成材料比较。"},
            {"message_id": 53, "role": "user", "content": "那么 SiC 呢"},
            {"message_id": 54, "role": "assistant", "content": "已完成 SiC 比较。"},
        ]
        with (
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", new=invalid_stream),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "是更前面的一个",
                history,
                "run-context-specific-clarification-test",
            ))

        self.assertEqual(result["intent_route"]["intent"], "unknown")
        self.assertEqual(result["context_resolution"]["resolution_state"], "unavailable")
        self.assertEqual(result["tool_trace"], [])
        self.assertIn("希望我回答或执行的内容", result["answer"])
        self.assertNotIn("消息 #", result["answer"])
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
            patch("app.agent_runtime.service._stream_completion", model_call),
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
            contract_message = next(
                item["content"] for item in request_payload["messages"]
                if item["role"] == "system" and "answer_contract=" in item["content"]
            )
            contract = json.loads(contract_message.split("answer_contract=", 1)[1])
            reference = next(item for item in contract["permitted_source_refs"] if item.startswith("TOOL:S"))
            semantic = contract["source_semantics"][reference]
            claim = {
                "claim_kind": semantic["kind"],
                "semantic_id": semantic["semantic_id"],
                "scope": semantic["scope"],
                "grain": semantic["grain"],
                "time_range": {},
                "claim_role": semantic["scope_role"],
            }
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
                                "conclusion_evidence_refs": [reference],
                                "conclusion_claim": claim,
                                "facts": [{
                                    "statement": "知识文档覆盖 GaN 与 Si 器件的基础流程差异。",
                                    "evidence_refs": [reference],
                                    **claim,
                                }],
                                "inferences": [],
                                "hypotheses": [],
                                "recommendations": [],
                                "limitations": [],
                                "source_refs": [reference, "KB-CONTEXT-001"],
                            }, ensure_ascii=False),
                        },
                    }],
                },
                {"total_tokens": 10},
                "context-submit-response",
            )

        with (
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: [source]}),
        ):
            result = asyncio.run(
                agent_module._run_agent_impl("最后一点", history, "run-context-follow-up-test")
            )

        self.assertEqual(result["context_resolution"]["strategy"], "ordinal_selection")
        self.assertEqual(result["intent_route"]["intent"], "sop_lookup")
        self.assertEqual(result["execution_plan"]["status"], "ready")
        self.assertEqual([item["tool"] for item in result["tool_trace"]], ["search_knowledge", "search_knowledge"])
        self.assertTrue(all(item["status"] == "ok" for item in result["tool_trace"]))
        self.assertEqual(calls, 1)
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
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", model_call),
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
        self.assertIn("请把希望我回答或执行的内容再写完整一些", result["answer"])
        follow_up = resolve_question_context(
            "最后一点",
            [
                {"role": "user", "content": "帮我比较两种器件"},
                {"role": "assistant", "content": result["answer"]},
            ],
        )
        self.assertTrue(follow_up.applied)
        self.assertEqual(route_question(follow_up.resolved_question).intent, "general_knowledge")
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
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", new=fake_stream),
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

    def test_capability_question_uses_semantic_conversation_hint_without_tools(self):
        model_call = AsyncMock(return_value=_context_response(
            "standalone", "你有什么功能", confidence=0.94, intent_hint="conversation",
        ))
        with patch("app.agent_runtime.service.get_settings", return_value=_settings()), patch("app.agent_runtime.service._stream_completion", model_call):
            result = asyncio.run(agent_module._run_agent_impl("你有什么功能", [], "run-capability-conversation"))

        self.assertEqual(result["intent_route"]["intent"], "conversation")
        self.assertEqual(result["tool_trace"], [])
        self.assertIn("Fab Copilot", result["answer"])

    def test_capability_correction_uses_semantic_conversation_hint_without_history_picker(self):
        model_call = AsyncMock(return_value=_context_response(
            "correction", "说明 Fab Copilot 的功能", "助手能力",
            confidence=0.94, intent_hint="conversation",
        ))
        history = [
            {"message_id": 1, "role": "user", "content": "你是谁"},
            {"message_id": 2, "role": "assistant", "content": "我是 Fab Copilot。"},
        ]
        with patch("app.agent_runtime.service.get_settings", return_value=_settings()), patch("app.agent_runtime.service._stream_completion", model_call):
            result = asyncio.run(agent_module._run_agent_impl(
                "我询问你的功能而不是需要指向某条历史消息", history, "run-capability-correction",
            ))

        self.assertEqual(result["intent_route"]["intent"], "conversation")
        self.assertEqual(result["tool_trace"], [])
        self.assertIn("身份、具体能力、使用方式", result["answer"])
        self.assertNotIn("消息 #", result["answer"])

    def test_context_timeout_never_lists_history_candidates(self):
        async def timeout_stream(*_args):
            raise httpx.ReadTimeout("simulated")

        history = [
            {"message_id": 1, "role": "user", "content": "你是谁"},
            {"message_id": 2, "role": "assistant", "content": "我是 Fab Copilot。"},
        ]
        with patch("app.agent_runtime.service.get_settings", return_value=_settings()), patch("app.agent_runtime.service._stream_completion", new=timeout_stream):
            result = asyncio.run(agent_module._run_agent_impl(
                "我询问你的功能而不是需要指向某条历史消息", history, "run-capability-timeout",
            ))

        self.assertEqual(result["context_resolution"]["resolution_state"], "unavailable")
        self.assertIn("希望我回答或执行的内容", result["answer"])
        self.assertNotIn("消息 #", result["answer"])

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
            return (
                {
                    "role": "assistant",
                    "content": "GaN 的宽禁带和高击穿场强通常适合高压与高频功率场景。",
                },
                {"total_tokens": 8},
                "fallback-submit-response",
            )

        with (
            patch("app.agent_runtime.service.get_settings", return_value=_settings()),
            patch("app.agent_runtime.service._stream_completion", new=fake_stream),
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
        self.assertEqual(round_number, 1)
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
