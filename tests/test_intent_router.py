from __future__ import annotations

import asyncio
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import agent as agent_module
from app.intent_runtime.routing import apply_semantic_intent_hint, route_question, routing_system_message
from app.manufacturing.processes import PROCESS_ALIASES


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

    def test_routes_open_manufacturing_diagnostics_without_clarification(self):
        questions = (
            "关于目前的制造数据你有什么改进建议",
            "帮我看看最近生产情况怎么样，有哪些风险点",
            "对当前工厂运行做一次健康检查",
            "全厂有哪些薄弱环节值得优先改善",
            "基于近期制造表现给出优化方向",
            "比较各站点表现并排出改善优先级",
            "总结一下产线瓶颈和提升机会",
            "比较设备健康和良率趋势",
            "Cpk 最差的设备有什么改进建议",
            "为我分析一下最近一周ETCH几台的情况",
            "为我分析一下最近一周刻蚀几台的情况",
            "为我分析一下最近一周刻蚀机台的情况",
            "分析一下最近一周的生产状况",
        )
        expected_tools = {
            "get_fab_overview", "get_yield_trend", "get_process_capability",
            "get_equipment_health", "get_equipment_productivity",
            "get_defect_pareto", "get_recent_excursions",
        }

        for question in questions:
            with self.subTest(question=question):
                route = route_question(question, current_date=date(2026, 7, 18))
                self.assertEqual(route.intent, "fab_diagnostic")
                self.assertFalse(route.clarification_needed)
                self.assertEqual(set(route.data_requirements), expected_tools)

    def test_open_manufacturing_scope_does_not_capture_knowledge_or_scope_free_requests(self):
        knowledge = route_question("为我介绍一下光刻原理", current_date=date(2026, 7, 18))
        unclear = route_question("帮我看看这个情况", current_date=date(2026, 7, 18))

        self.assertEqual(knowledge.intent, "general_knowledge")
        self.assertFalse(knowledge.clarification_needed)
        self.assertEqual(unclear.intent, "unknown")
        self.assertTrue(unclear.clarification_needed)

    def test_unknown_manufacturing_scope_requires_clarification_without_special_case_mapping(self):
        for mention in ("PH", "ABC", "LINE-X7"):
            with self.subTest(mention=mention):
                route = route_question(
                    f"分析一下最近{mention}的生产状况",
                    current_date=date(2026, 7, 20),
                )

                self.assertEqual(route.intent, "fab_diagnostic")
                self.assertEqual(route.process_steps, ())
                self.assertEqual(route.scope_resolution.scope_type, "unknown")
                self.assertEqual(route.scope_resolution.unresolved_mentions, (mention,))
                self.assertTrue(route.scope_resolution.clarification_needed)
                self.assertTrue(route.clarification_needed)
                self.assertIn(mention, route.clarification_questions[0])

    def test_scope_resolution_distinguishes_fab_process_equipment_and_product(self):
        cases = (
            ("分析一下最近的生产状况", "fab", ("FAB",)),
            ("分析最近一周光刻机台状况", "process", ("LITHO",)),
            ("检查 ETCH-04 最近一周的故障", "equipment", ("ETCH-04",)),
            ("分析 Nova-P1 的生产状况", "product", ("Nova-P1",)),
        )
        for question, scope_type, resolved_ids in cases:
            with self.subTest(question=question):
                route = route_question(question, current_date=date(2026, 7, 20))
                self.assertEqual(route.scope_resolution.scope_type, scope_type)
                self.assertEqual(route.scope_resolution.resolved_ids, resolved_ids)
                self.assertFalse(route.scope_resolution.clarification_needed)

    def test_routes_operational_reviews_for_every_manufacturing_process_family(self):
        cases = (
            ("分析最近一周光刻机台状况", "LITHO"),
            ("查看过去7天刻蚀设备运行情况", "ETCH"),
            ("评估近两周CVD生产表现", "CVD"),
            ("盘点最近一周溅射设备现状", "PVD"),
            ("总结近7天炉管运行状态", "DIFFUSION"),
            ("分析最近一周离子注入生产状况", "IMPLANT"),
            ("评估过去7天CMP机台表现", "CMP"),
            ("查看近两周清洗设备情况", "CLEAN"),
            ("分析最近一周量测机台状况", "METROLOGY"),
        )

        for question, process_step in cases:
            with self.subTest(question=question):
                route = route_question(question, current_date=date(2026, 7, 18))
                self.assertEqual(route.intent, "fab_diagnostic")
                self.assertEqual(route.process_steps, (process_step,))
                self.assertFalse(route.clarification_needed)
                self.assertEqual(len(route.data_requirements), 7)

        for process_step, aliases in PROCESS_ALIASES.items():
            for alias in (process_step, *aliases):
                question = f"分析最近一周{alias}设备运行情况"
                with self.subTest(process_step=process_step, alias=alias):
                    route = route_question(question, current_date=date(2026, 7, 18))
                    self.assertEqual(route.intent, "fab_diagnostic")
                    self.assertEqual(route.process_steps, (process_step,))
                    self.assertFalse(route.clarification_needed)

    def test_diagnostic_routing_message_allows_required_manufacturing_tools(self):
        route = route_question(
            "关于目前的制造数据你有什么改进建议",
            current_date=date(2026, 7, 18),
        )

        message = routing_system_message(route)

        self.assertIn("其他制造意图应优先使用 data_requirements", message)
        self.assertNotIn("conversation 时由服务端直接回答助手身份与能力，不检索知识库或制造数据；不得调用", message)

    def test_diagnostic_language_preserves_single_domain_intents(self):
        cases = (
            ("CMP 良率下降有什么改善建议", "yield_decline"),
            ("ETCH-04 哪些设备风险需要优先处理", "equipment_fault"),
            ("分析 CVD 颗粒缺陷并给改善建议", "defect_analysis"),
            ("追踪批次 L260708-02460 并给出处置建议", "lot_trace"),
            ("工厂良率有什么改善建议", "yield_decline"),
            ("全厂设备风险有哪些", "equipment_fault"),
        )

        for question, expected in cases:
            with self.subTest(question=question):
                route = route_question(question, current_date=date(2026, 7, 18))
                self.assertEqual(route.intent, expected)
                self.assertFalse(route.clarification_needed)

    def test_relative_range_is_inclusive(self):
        route = route_question("最近7天 CMP-03 Cpk", current_date=date(2026, 7, 18))

        self.assertEqual(route.time_range.start, "2026-07-12")
        self.assertEqual(route.time_range.end, "2026-07-18")
        self.assertEqual(route.time_range.source, "relative")

        chinese_amount = route_question("最近四周良率下降", current_date=date(2026, 7, 18))
        self.assertEqual(chinese_amount.time_range.start, "2026-06-21")
        self.assertEqual(chinese_amount.time_range.end, "2026-07-18")

    def test_marks_close_conjoined_intents_without_diagnostic_goal_as_ambiguous(self):
        route = route_question("设备健康和良率趋势", current_date=date(2026, 7, 18))

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

    def test_semantic_hint_only_promotes_unknown_general_knowledge(self):
        route = route_question("当前主流制程有哪些", current_date=date(2026, 7, 18))

        general = apply_semantic_intent_hint(route, "general_knowledge", 0.92)
        manufacturing = apply_semantic_intent_hint(route, "manufacturing_analysis", 0.99)

        self.assertEqual(general.intent, "general_knowledge")
        self.assertFalse(general.clarification_needed)
        self.assertEqual(general.data_requirements, ("search_knowledge",))
        self.assertEqual(manufacturing.intent, "unknown")
        self.assertTrue(manufacturing.clarification_needed)

    def test_semantic_conversation_hint_promotes_only_unknown_to_zero_tool_path(self):
        unknown = route_question("你是？", current_date=date(2026, 7, 18))
        manufacturing = route_question("分析最近四周良率", current_date=date(2026, 7, 18))

        conversation = apply_semantic_intent_hint(unknown, "conversation", 0.92)
        unchanged = apply_semantic_intent_hint(manufacturing, "conversation", 0.99)

        self.assertEqual(unknown.intent, "unknown")
        self.assertEqual(conversation.intent, "conversation")
        self.assertEqual(conversation.data_requirements, ())
        self.assertEqual(conversation.risk_level, "low")
        self.assertFalse(conversation.clarification_needed)
        self.assertEqual(unchanged.intent, "yield_decline")

    def test_semantic_meta_conversation_uses_context_model_only(self):
        question = "你是？"
        self.assertEqual(route_question(question, current_date=date(2026, 7, 18)).intent, "unknown")
        cases = (
            ("first_turn", []),
            ("unrelated_history", [
                {"message_id": 1, "role": "user", "content": "解释一下 CMP 的作用。"},
                {"message_id": 2, "role": "assistant", "content": "CMP 用于晶圆表面平坦化。"},
            ]),
        )

        for case_name, history in cases:
            with self.subTest(case=case_name):
                model_call = AsyncMock(return_value=(
                    {
                        "role": "assistant",
                        "content": json.dumps({
                            "relation": "standalone",
                            "resolved_question": question,
                            "topic_anchor": "",
                            "target_message_ids": [],
                            "confidence": 0.94,
                            "intent_hint": "conversation",
                        }, ensure_ascii=False),
                    },
                    {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
                    "context-conversation-response",
                ))

                with (
                    patch("app.agent.get_settings", return_value=SimpleNamespace(
                        model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
                        api_timeout_seconds=5,
                        model_max_retries=0,
                        model_retry_base_seconds=0.05,
                    )),
                    patch("app.agent._stream_completion", model_call),
                ):
                    result = asyncio.run(agent_module._run_agent_impl(
                        question, history, f"run-semantic-conversation-{case_name}",
                    ))

                model_call.assert_awaited_once()
                self.assertEqual(result["intent_route"]["intent"], "conversation")
                self.assertEqual(result["tool_trace"], [])
                self.assertEqual(result["retrieval_decision"]["state"], "NOT_APPLICABLE")
                self.assertFalse(result["knowledge_fallback"]["used"])
                self.assertNotIn("个人知识库和工厂知识库", result["answer"])
                self.assertNotIn("未检索到", result["answer"])

    def test_semantic_followup_hint_can_correct_source_driven_sop_route(self):
        route = route_question("优先使用我的个人知识库继续介绍光刻")
        self.assertEqual(route.intent, "sop_lookup")

        standalone = apply_semantic_intent_hint(
            route,
            "general_knowledge",
            0.94,
            context_applied=False,
        )
        followup = apply_semantic_intent_hint(
            route,
            "general_knowledge",
            0.94,
            context_applied=True,
        )

        self.assertEqual(standalone.intent, "sop_lookup")
        self.assertEqual(followup.intent, "general_knowledge")
        self.assertEqual(followup.data_requirements, ("search_knowledge",))
        self.assertFalse(followup.clarification_needed)

    def test_semantic_general_hint_never_overrides_manufacturing_route(self):
        route = route_question("分析最近四周良率")
        corrected = apply_semantic_intent_hint(
            route,
            "general_knowledge",
            0.99,
            context_applied=True,
        )

        self.assertEqual(corrected.intent, "yield_decline")

    def test_general_comparison_does_not_request_production_scope(self):
        route = route_question("GAN器件和S器件的差别", current_date=date(2026, 7, 18))

        self.assertEqual(route.intent, "general_knowledge")
        self.assertEqual(route.data_requirements, ("search_knowledge",))
        self.assertEqual(route.risk_level, "low")
        self.assertFalse(route.clarification_needed)

    def test_educational_advantage_question_routes_to_general_knowledge(self):
        route = route_question(
            "为我科普一下GAN器件在做电源的时候相较Si的优势",
            current_date=date(2026, 7, 18),
        )

        self.assertEqual(route.intent, "general_knowledge")
        self.assertEqual(route.data_requirements, ("search_knowledge",))
        self.assertFalse(route.clarification_needed)

    def test_self_introduction_is_deterministic_conversation_without_rag(self):
        route = route_question("介绍一下你自己", current_date=date(2026, 7, 18))
        self.assertEqual(route.intent, "conversation")
        self.assertEqual(route.data_requirements, ())
        self.assertFalse(route.clarification_needed)

        model_call = AsyncMock(side_effect=AssertionError("conversation must not call model"))
        with (
            patch("app.agent.get_settings", return_value=SimpleNamespace(
                model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
                api_timeout_seconds=5,
                model_max_retries=0,
                model_retry_base_seconds=0.05,
            )),
            patch("app.agent._stream_completion", model_call),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "介绍一下你自己", [], "run-conversation-test",
            ))

        model_call.assert_not_awaited()
        self.assertEqual(result["mode"], "deterministic")
        self.assertEqual(result["tool_trace"], [])
        self.assertIn("Fab Copilot", result["answer"])
        self.assertNotIn("未检索到", result["answer"])

    def test_general_agent_path_searches_private_and_factory_before_model(self):
        captured: dict = {}
        search_calls: list[dict] = []
        personal_source = {
            "reference_id": "PERSONAL-GAN-001",
            "source_type": "personal",
            "title": "GaN 与 Si 器件笔记",
            "section": "材料差异",
            "excerpt": "GaN 是宽禁带半导体，Si 是传统硅半导体。",
            "retrieval": {"confidence": "high", "final_score": 5.0},
        }

        def fake_search(**arguments):
            search_calls.append(arguments)
            return [personal_source] if arguments["source_types"] == ["personal"] else []

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            captured.update(request_payload)
            return (
                {
                    "role": "assistant",
                    "content": "我暂按 S 指 Si 理解。GaN 是宽禁带半导体，Si 是传统硅半导体。[来源 PERSONAL-GAN-001]",
                },
                {"total_tokens": 8},
                "general-knowledge-response",
            )

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": fake_search}),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "GAN器件和S器件的差别", [], "run-general-knowledge-test",
            ))

        self.assertEqual(result["intent_route"]["intent"], "general_knowledge")
        self.assertEqual(result["execution_plan"]["status"], "unsupported")
        self.assertEqual(result["retrieval_decision"]["state"], "GROUND_PERSONAL")
        self.assertFalse(result["knowledge_fallback"]["used"])
        self.assertEqual(len(result["tool_trace"]), 4)
        self.assertEqual(
            {tuple(item["source_types"]) for item in search_calls},
            {("personal",), ("knowledge",)},
        )
        self.assertNotIn("tools", captured)
        self.assertNotIn("tool_choice", captured)
        self.assertIn("GaN", result["answer"])
        self.assertEqual(result["sources"][0]["reference_id"], "PERSONAL-GAN-001")

    def test_general_agent_falls_back_only_after_all_scopes_and_rewrite_are_empty(self):
        search_calls: list[dict] = []

        def empty_search(**arguments):
            search_calls.append(arguments)
            return []

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            return (
                {"role": "assistant", "content": "我暂按 S 指 Si 理解。GaN 与 Si 的材料特性不同。"},
                {"total_tokens": 6},
                "general-fallback-response",
            )

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": empty_search}),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "GAN器件和S器件的差别", [], "run-general-fallback-test",
            ))

        self.assertEqual(len(search_calls), 4)
        self.assertEqual(result["retrieval_decision"]["state"], "MODEL_ONLY_FALLBACK")
        self.assertEqual(result["retrieval_decision"]["rewritten_query"], "GaN器件和Si器件的差别")
        self.assertTrue(result["knowledge_fallback"]["used"])
        self.assertIn("个人知识库和工厂知识库", result["answer"])
        self.assertIn("模型通用知识", result["answer"])

    def test_general_agent_does_not_duplicate_semantic_fallback_disclosure(self):
        disclosed_answer = (
            "个人知识库和工厂知识库均未检索到相关内容。"
            "以下根据模型通用知识回答，仅供参考。\n\nGaN 与 Si 的材料特性不同。"
        )

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            stream_state["answer_emitted"] = True
            return (
                {"role": "assistant", "content": disclosed_answer},
                {"total_tokens": 6},
                "general-disclosed-response",
            )

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: []}),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "GAN器件和S器件的差别", [], "run-general-disclosure-test",
            ))

        self.assertEqual(result["answer"], disclosed_answer)
        self.assertEqual(result["answer"].count("个人知识库和工厂知识库"), 1)

    def test_general_agent_unwraps_model_tool_json_before_streaming(self):
        progress_events: list[dict] = []

        async def progress(event: dict) -> None:
            progress_events.append(event)

        async def fake_stream(client, endpoint, headers, request_payload, callback, stream_state):
            self.assertIsNotNone(callback)
            wrapped = {
                "tool_calls": [{
                    "id": "fake-submit",
                    "type": "function",
                    "function": {
                        "name": "submit_analysis",
                        "arguments": {
                            "content": "我暂按 S 指 Si 理解。\n\nGaN 是宽禁带半导体。",
                        },
                    },
                }],
            }
            return (
                {"role": "assistant", "content": "```json\n" + json.dumps(wrapped, ensure_ascii=False) + "\n```"},
                {"total_tokens": 6},
                "wrapped-general-response",
            )

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"search_knowledge": lambda **_: []}),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "GAN器件和S器件的差别", [], "run-general-json-repair-test", progress,
            ))

        self.assertNotIn("tool_calls", result["answer"])
        self.assertNotIn("```json", result["answer"])
        self.assertIn("GaN 是宽禁带半导体", result["answer"])
        streamed = "".join(
            item.get("delta", "") for item in progress_events if item.get("event") == "answer_delta"
        )
        self.assertEqual(streamed, result["answer"])

    def test_agent_loop_injects_and_returns_structured_route(self):
        captured: dict = {}
        progress_events: list[dict] = []

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            captured.update(request_payload)
            return ({"role": "assistant", "content": "路由测试完成"}, {"total_tokens": 3}, "route-response")

        async def progress(event: dict) -> None:
            progress_events.append(event)

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
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
        synthesis_task = json.loads(captured["messages"][-1]["content"])
        self.assertEqual(synthesis_task["intent"], "capability_excursion")
        self.assertEqual(synthesis_task["scope"], {"type": "equipment", "ids": ["CMP-03"]})
        self.assertEqual(
            [tool["function"]["name"] for tool in captured["tools"]],
            ["submit_analysis"],
        )


if __name__ == "__main__":
    unittest.main()
