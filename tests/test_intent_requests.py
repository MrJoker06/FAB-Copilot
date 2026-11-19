"""Human-labelled routing cases and actual contextual arbitration boundaries."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.conversation.decision_arbiter import arbitrate_decision
from app.intent_runtime.routing import route_question
from app.memory_system.context.resolver import semantic_context_resolution
from scripts.evaluate_intent_routing import evaluate

ROOT = Path(__file__).resolve().parents[1]


class IntentRequestTests(unittest.TestCase):
    def test_empty_or_duplicate_labelled_cases_cannot_pass_evaluation(self):
        with self.assertRaises(ValueError):
            evaluate(route_question, {"cases": []})
        with self.assertRaises(ValueError):
            evaluate(route_question, {"cases": [{"id": "same"}, {"id": "same"}]})

    def test_independently_labelled_execution_types_and_topics(self):
        gold = json.loads(
            (ROOT / "evaluations/intent_request_gold.json").read_text(encoding="utf-8")
        )
        result = evaluate(route_question, gold)
        for case in result["results"]:
            with self.subTest(case=case["id"]):
                self.assertTrue(case["decision_correct"], case)
                self.assertTrue(case["request_type_correct"], case)
                self.assertTrue(case["topics_correct"], case)

    def arbitrate(
        self,
        question,
        resolved,
        *,
        active="task:general_knowledge",
        confidence=0.95,
        hint="manufacturing_analysis",
        history=None,
    ):
        context = semantic_context_resolution(
            question,
            {
                "relation": "followup",
                "resolved_question": resolved,
                "topic_anchor": "Cpk",
                "target_message_ids": [],
                "confidence": confidence,
                "intent_hint": hint,
            },
        )
        return arbitrate_decision(
            original_question=question,
            resolved_question=context.resolved_question,
            original_route=route_question(question),
            resolved_route=route_question(context.resolved_question),
            context=context,
            previous_active_flow=active,
            history=history,
        )

    def test_explicit_query_followup_can_switch_from_concept_to_actual_data(self):
        result = self.arbitrate("那查一下昨天的数据", "查询昨天 CMP 的 Cpk", history=[{"role": "user", "content": "解释 CMP 制程能力的定义"}])
        self.assertEqual(result.route.intent, "capability_excursion")
        self.assertEqual(result.route.request_type, "data_query")
        self.assertEqual(result.effective_question, "查询昨天 CMP 的 Cpk")
        self.assertEqual(result.policy_reason, "explicit_request_type_followup")

    def test_model_expansion_cannot_invent_scope_or_replace_explicit_dates(self):
        for history, expanded in (
            ([], "查询昨天 CMP 的 Cpk"),
            ([{"role": "assistant", "content": "CMP 的 Cpk"}], "查询昨天 CMP 的 Cpk"),
            ([{"role": "user", "content": "解释 ETCH 制程能力"}], "查询昨天 CMP 的 Cpk"),
            ([{"role": "user", "content": "解释 CMP 制程能力"}], "查询 2026-01-01 CMP 的 Cpk"),
        ):
            with self.subTest(history=history, expanded=expanded):
                result = self.arbitrate("那查一下昨天的数据", expanded, history=history)
                self.assertEqual(result.route.intent, "unknown")
                self.assertTrue(result.route.clarification_needed)

    def test_stale_manufacturing_context_cannot_override_an_explicit_concept_question(
        self,
    ):
        result = self.arbitrate(
            "什么是 Cpk", "分析昨天 CMP Cpk 漂移", active="task:capability_excursion"
        )
        self.assertEqual(
            (result.route.intent, result.route.request_type),
            ("general_knowledge", "explanation"),
        )
        self.assertEqual(result.route.data_requirements, ("search_knowledge",))
        self.assertEqual(result.effective_question, "什么是 Cpk")

    def test_unknown_or_low_confidence_followup_never_activates_an_expanded_task(self):
        for question, confidence, active in (
            ("这个呢", 0.95, "task:general_knowledge"),
            ("那查一下昨天的数据", 0.4, "task:general_knowledge"),
            ("那查一下昨天的数据", 0.95, None),
        ):
            with self.subTest(question=question, confidence=confidence, active=active):
                result = self.arbitrate(
                    question,
                    "查询昨天 CMP 的 Cpk",
                    active=active,
                    confidence=confidence,
                )
                self.assertNotEqual(result.route.intent, "capability_excursion")

    def test_semantic_hint_cannot_hide_literal_data_request_as_knowledge(self):
        result = self.arbitrate(
            "查一下昨天的数据", "解释 Cpk 是什么", hint="general_knowledge"
        )
        self.assertEqual(result.route.intent, "unknown")
        self.assertTrue(result.route.clarification_needed)

    def test_negated_equipment_does_not_leak_into_scope(self):
        route = route_question("不要看 ETCH-04，查看 CMP-02 最近7天健康")
        self.assertEqual(route.equipment_ids, ("CMP-02",))
        self.assertEqual(route.process_steps, ("CMP",))

    def test_explanation_followup_keeps_the_topic_without_inheriting_data_execution(
        self,
    ):
        result = self.arbitrate(
            "只解释原理",
            "解释 CMP 制程能力原理",
            active="task:capability_excursion",
            hint="general_knowledge",
        )
        self.assertEqual(result.route.intent, "general_knowledge")
        self.assertEqual(result.route.request_type, "explanation")
        self.assertIn("capability", result.route.business_topics)
        self.assertEqual(result.effective_question, "解释 CMP 制程能力原理")

    def test_mixed_request_cannot_be_resolved_away_by_existing_knowledge_flow(self):
        result = self.arbitrate(
            "解释 Cpk 并查询昨天 CMP 的 Cpk", "解释 Cpk", hint="general_knowledge"
        )
        self.assertEqual(result.route.intent, "ambiguous")
        self.assertTrue(result.route.clarification_needed)

    def test_query_followup_cannot_invent_a_lot_and_plan_ignores_negated_lot(self):
        result = self.arbitrate("那查一下昨天的数据", "查询昨天 LOT-999 批次履历", active="task:lot_trace", history=[{"role": "user", "content": "查询 LOT-001 批次履历"}])
        self.assertEqual(result.route.intent, "unknown")
        from app.planning_runtime.named_playbooks import select_named_playbook
        from app.planning_runtime.service import create_execution_plan
        question = "不要查 LOT-999，查询 LOT-001 批次履历"
        route = route_question(question)
        plan = create_execution_plan(question, route, select_named_playbook(route))
        self.assertEqual(plan.status, "ready")
        lot_parameters = [step.parameters["lot_id"] for step in plan.steps if "lot_id" in step.parameters]
        self.assertTrue(lot_parameters)
        self.assertEqual(set(lot_parameters), {"LOT-001"})
