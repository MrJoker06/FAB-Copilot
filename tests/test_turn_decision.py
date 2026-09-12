from __future__ import annotations
import unittest
import importlib
from app.agent import TOOL_HANDLERS

from app.agent_runtime.assistant_capabilities import CAPABILITIES, build_meta_response, user_capabilities
from app.conversation.turn_decision import TurnDecisionValidationError, build_turn_decision, validate_turn_actions
from app.intent_router import route_question
from app.conversation.context_resolver import semantic_context_resolution
from app.conversation.decision_arbiter import arbitrate_decision, recover_active_flow


class TurnDecisionTests(unittest.TestCase):
    def test_canonical_identity_and_capability_are_distinct(self):
        identity = build_turn_decision(route="conversation", relation="standalone", confidence=1, question="你是谁")
        capabilities = build_turn_decision(route="conversation", relation="standalone", confidence=1, question="你有什么功能")
        self.assertEqual(identity.actions[0].subject, "identity")
        self.assertEqual(capabilities.actions[0].subject, "capabilities")
        self.assertNotEqual(build_meta_response("identity", "brief")[0], build_meta_response("capabilities", "standard")[0])

    def test_model_correction_supports_detailed_capabilities(self):
        decision = build_turn_decision(route="conversation", relation="correction", confidence=.9, question="具体能力", model_actions=[{"type":"answer_meta","subject":"capabilities","detail":"detailed"}])
        answer, ids = build_meta_response(decision.actions[0].subject, decision.actions[0].detail)
        self.assertEqual(decision.source, "model")
        self.assertIn("例如：", answer)
        self.assertIn("限制：", answer)
        self.assertEqual(len(ids), len(user_capabilities()))

    def test_invalid_actions_do_not_create_tool_surface(self):
        with self.assertRaises(TurnDecisionValidationError):
            validate_turn_actions([{"type":"route_task","target_intent":"get_yield_trend"}], allowed_route_intents={"yield_decline"})
        decision = build_turn_decision(route="conversation", relation="correction", confidence=.9, question="具体能力", model_actions=[{"type":"answer_meta","subject":"capabilities","sql":"select 1"}])
        self.assertEqual(decision.actions[0].type, "clarify")

    def test_non_conversation_only_hands_off_to_existing_route(self):
        decision = build_turn_decision(route="yield_decline", relation="standalone", confidence=.9, question="昨天良率")
        self.assertEqual(decision.actions[0].target_intent, "yield_decline")

    def test_catalog_hides_admin_and_backing_references_are_real(self):
        self.assertNotIn("model_governance", [item.capability_id for item in user_capabilities()])
        for item in CAPABILITIES:
            for reference in item.backing_references:
                kind, value = reference.split(":", 1)
                if kind == "TOOL_HANDLERS": self.assertIn(value, TOOL_HANDLERS)
                else: self.assertIsNotNone(importlib.util.find_spec(value))

    def test_unknown_and_ambiguous_are_valid_clarifications(self):
        for route in ("unknown", "ambiguous"):
            decision = build_turn_decision(route=route, relation="standalone", confidence=0, question="这个")
            self.assertEqual(decision.actions[0].type, "clarify")

    def test_acknowledge_before_primary_selects_primary(self):
        decision = build_turn_decision(route="conversation", relation="followup", confidence=.9, question="展开", model_actions=[{"type":"acknowledge"}, {"type":"answer_meta","subject":"capabilities","detail":"detailed"}])
        self.assertEqual(decision.actions[1].subject, "capabilities")

    def test_assistant_capability_question_does_not_execute_manufacturing_route(self):
        self.assertEqual(route_question("你能查良率吗").intent, "conversation")
        self.assertEqual(route_question("那就查昨天良率").intent, "yield_decline")
        self.assertEqual(route_question("分析 CMP 制程能力").intent, "capability_excursion")

    def test_runtime_status_reports_actual_thinking_policy(self):
        response, _ = build_meta_response("runtime_status", "standard", runtime_context={"thinking_requested": True})
        self.assertIn("已请求", response); self.assertIn("effective=false", response)

    def test_active_meta_flow_wins_over_expansion_source_words(self):
        for source_word in ("文档", "知识库", "规范"):
            with self.subTest(source_word=source_word):
                context = semantic_context_resolution(
                    "具体一点",
                    {
                        "relation": "followup",
                        "resolved_question": f"请详细说明 Fab Copilot 的功能，以及个人{source_word}管理能力",
                        "topic_anchor": "助手能力",
                        "target_message_ids": [],
                        "confidence": .95,
                        "intent_hint": "conversation",
                        "turn_actions": [{"type": "answer_meta", "subject": "capabilities", "detail": "detailed"}],
                    },
                )
                result = arbitrate_decision(
                    original_question="具体一点",
                    resolved_question=context.resolved_question,
                    original_route=route_question("具体一点"),
                    resolved_route=route_question(context.resolved_question),
                    context=context,
                    raw_model_actions=list(context.turn_actions),
                    previous_active_flow="meta:capabilities",
                )
                self.assertEqual(result.route.intent, "conversation")
                self.assertEqual(result.model_actions[0].subject, "capabilities")
                self.assertEqual(result.active_flow, "meta:capabilities")
                self.assertEqual(result.selected_origin, "semantic_context")
                self.assertEqual(result.policy_reason, "active_meta_flow_continuation")
                self.assertTrue(any(item.status == "selected" for item in result.candidates))

    def test_explicit_task_switches_out_of_meta_flow(self):
        context = semantic_context_resolution(
            "那就查昨天良率",
            {"relation": "followup", "resolved_question": "查昨天 CMP 良率", "topic_anchor": "能力", "target_message_ids": [], "confidence": .95, "intent_hint": "conversation"},
        )
        for question, expected in (("那就查昨天良率", "yield_decline"), ("分析 CMP 制程能力", "capability_excursion"), ("查一下 CMP SOP/规范", "sop_lookup")):
            with self.subTest(question=question):
                route = route_question(question)
                result = arbitrate_decision(
                    original_question=question, resolved_question=question,
                    original_route=route, resolved_route=route, context=context,
                    previous_active_flow="meta:capabilities",
                )
                self.assertEqual(result.route.intent, expected)
                self.assertEqual(result.selected_origin, "original_text")
                self.assertEqual(result.policy_reason, "explicit_original_task")
                self.assertEqual(result.active_flow, f"task:{expected}")

    def test_old_or_invalid_flow_and_low_confidence_actions_do_not_bind(self):
        self.assertIsNone(recover_active_flow([{"role": "assistant", "metadata": {"turn_decision": {"active_flow": "tool:get_yield_trend"}}}]))
        context = semantic_context_resolution(
            "这个再细一点",
            {"relation": "followup", "resolved_question": "查看知识库文档", "topic_anchor": "能力", "target_message_ids": [], "confidence": .4, "intent_hint": "conversation", "turn_actions": [{"type": "answer_meta", "subject": "capabilities", "detail": "detailed"}]},
        )
        result = arbitrate_decision(
            original_question="这个再细一点", resolved_question=context.resolved_question,
            original_route=route_question("这个再细一点"), resolved_route=route_question(context.resolved_question),
            context=context, raw_model_actions=list(context.turn_actions), previous_active_flow=None,
        )
        self.assertEqual(result.route.intent, "conversation")
        self.assertEqual(result.policy_reason, "trusted_context_clarification")
        self.assertEqual(result.model_actions, ())

    def test_context_clarification_cannot_override_explicit_manufacturing_task(self):
        context = semantic_context_resolution(
            "那就查昨天良率",
            {"relation": "followup", "resolved_question": "这个问题", "topic_anchor": "能力", "target_message_ids": [], "confidence": .4, "intent_hint": "unclear"},
        )
        self.assertEqual(context.strategy, "context_clarification")
        result = arbitrate_decision(
            original_question="那就查昨天良率", resolved_question=context.resolved_question,
            original_route=route_question("那就查昨天良率"), resolved_route=route_question(context.resolved_question), context=context,
            previous_active_flow="meta:capabilities",
        )
        self.assertEqual(result.route.intent, "yield_decline")
        self.assertEqual(result.active_flow, "task:yield_decline")
        self.assertEqual(result.policy_reason, "explicit_original_task")

    def test_only_latest_assistant_metadata_can_restore_active_flow(self):
        history = [
            {"role": "assistant", "metadata": {"turn_decision": {"active_flow": "meta:capabilities"}}},
            {"role": "user", "content": "查昨天良率"},
            {"role": "assistant", "metadata": {}},
        ]
        self.assertIsNone(recover_active_flow(history))

    def test_general_knowledge_preference_never_overrides_explicit_manufacturing_task(self):
        question = "分析昨天良率，但优先参考知识库"
        context = semantic_context_resolution(
            question,
            {"relation": "correction", "resolved_question": "优先使用知识库中的文档", "topic_anchor": "良率", "target_message_ids": [], "confidence": .95, "intent_hint": "general_knowledge"},
        )
        result = arbitrate_decision(
            original_question=question, resolved_question=context.resolved_question,
            original_route=route_question(question), resolved_route=route_question(context.resolved_question), context=context,
        )
        self.assertEqual(result.route.intent, "yield_decline")
        self.assertEqual(result.policy_reason, "explicit_original_task")

    def test_active_task_flow_continues_only_same_resolved_task(self):
        context = semantic_context_resolution(
            "最近一周呢",
            {"relation": "followup", "resolved_question": "分析最近一周良率", "topic_anchor": "良率", "target_message_ids": [], "confidence": .95, "intent_hint": "manufacturing_analysis"},
        )
        result = arbitrate_decision(
            original_question="最近一周呢", resolved_question=context.resolved_question,
            original_route=route_question("最近一周呢"), resolved_route=route_question(context.resolved_question),
            context=context, previous_active_flow="task:yield_decline",
        )
        self.assertEqual(result.route.intent, "yield_decline")
        self.assertEqual(result.effective_question, "分析最近一周良率")
        self.assertEqual(result.active_flow, "task:yield_decline")
        self.assertEqual(result.policy_reason, "active_task_flow_continuation")

        mismatched = arbitrate_decision(
            original_question="最近一周呢", resolved_question="检查 ETCH-01 设备故障",
            original_route=route_question("最近一周呢"), resolved_route=route_question("检查 ETCH-01 设备故障"),
            context=context, previous_active_flow="task:yield_decline",
        )
        self.assertNotEqual(mismatched.route.intent, "equipment_fault")
        self.assertEqual(mismatched.effective_question, "最近一周呢")

    def test_explicit_task_uses_original_question_not_malformed_expansion(self):
        question = "分析昨天良率，但优先参考知识库"
        context = semantic_context_resolution(
            question,
            {"relation": "correction", "resolved_question": "优先使用知识库中的文档", "topic_anchor": "良率", "target_message_ids": [], "confidence": .95, "intent_hint": "general_knowledge"},
        )
        result = arbitrate_decision(
            original_question=question, resolved_question=context.resolved_question,
            original_route=route_question(question), resolved_route=route_question(context.resolved_question), context=context,
        )
        self.assertEqual(result.route.intent, "yield_decline")
        self.assertEqual(result.effective_question, question)
