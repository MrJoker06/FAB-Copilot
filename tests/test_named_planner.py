from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from app.intent_runtime.routing import route_question
from app.planning_runtime.named_playbooks import (
    NAMED_DOMAIN_PLAYBOOKS,
    NAMED_PLAYBOOK_VERSION,
    select_named_playbook,
)
from app.planning_runtime.playbooks import select_playbook
from app.planning_runtime.named_planner import (
    NamedPlannerError,
    create_named_execution_plan,
)
from app.planning_runtime.service import create_execution_plan


class NamedPlannerTests(unittest.TestCase):
    current_date = date(2026, 10, 31)

    def test_lot_trace_uses_only_named_queries_without_date_clipping(self) -> None:
        question = "追踪 LOT-0001-001 的完整历史"
        route = route_question(question, self.current_date)
        plan = create_named_execution_plan(question, route)

        self.assertEqual((plan.schema_version, plan.planner_version), ("1.2", "2.0.0"))
        self.assertTrue(plan.plan_id.startswith("named-2.0.0-plan-"))
        self.assertEqual(
            [step.tool for step in plan.steps[:5]],
            [
                "get_lot_identity",
                "get_lot_process_history",
                "get_lot_excursion_history",
                "get_lot_defect_history",
                "get_lot_wafer_map_patterns",
            ],
        )
        for step in plan.steps[:5]:
            self.assertEqual(step.parameters, {"lot_id": "LOT-0001-001"})
            self.assertIsNone(step.evidence_start)
            self.assertIsNone(step.evidence_end)
        self.assertEqual(plan.steps[0].estimated_result_limit, 10)
        self.assertNotIn("query_manufacturing_data", [step.tool for step in plan.steps])

    def test_v2_playbooks_replace_each_fixed_sql_evidence(self) -> None:
        expected = {
            "YLD-02": "get_product_yield_breakdown",
            "EQP-03": "get_equipment_event_timeline",
            "EQP-04": "get_equipment_excursion_history",
            "LOT-01": "get_lot_identity",
            "LOT-02": "get_lot_process_history",
            "LOT-03": "get_lot_wafer_map_patterns",
        }
        actual = {
            requirement.evidence_id: requirement.source_tools
            for playbook in NAMED_DOMAIN_PLAYBOOKS.values()
            for requirement in playbook.evidence_requirements
        }
        for evidence_id, tool in expected.items():
            with self.subTest(evidence_id=evidence_id):
                self.assertIn(tool, actual[evidence_id])
                self.assertNotIn("query_manufacturing_data", actual[evidence_id])
        self.assertTrue(
            all(
                playbook.playbook_version == NAMED_PLAYBOOK_VERSION
                for playbook in NAMED_DOMAIN_PLAYBOOKS.values()
            )
        )

    def test_product_and_joint_equipment_parameters_have_explicit_scope(self) -> None:
        product_question = "Nova-P1 最近7天良率下降"
        product_plan = create_named_execution_plan(
            product_question, route_question(product_question, self.current_date)
        )
        product = next(
            step
            for step in product_plan.steps
            if step.tool == "get_product_yield_breakdown"
        )
        self.assertEqual(product.parameters["product"], "Nova-P1")
        self.assertEqual(product.evidence_scope["products"], ("NOVA-P1",))

        equipment_question = "CMP-01 最近7天故障"
        equipment_plan = create_named_execution_plan(
            equipment_question, route_question(equipment_question, self.current_date)
        )
        timeline = next(
            step
            for step in equipment_plan.steps
            if step.tool == "get_equipment_event_timeline"
        )
        excursion = next(
            step
            for step in equipment_plan.steps
            if step.tool == "get_equipment_excursion_history"
        )
        self.assertEqual(
            timeline.parameters,
            {
                "start": "2026-10-25",
                "end": "2026-10-31",
                "equipment_id": "CMP-01",
            },
        )
        self.assertEqual(excursion.evidence_scope["process_steps"], ("CMP",))
        self.assertEqual(excursion.evidence_scope["equipment_ids"], ("CMP-01",))

    def test_legacy_selection_is_rejected_and_legacy_plan_stays_sql_based(self) -> None:
        question = "追踪 LOT-0001-001"
        route = route_question(question, self.current_date)
        with self.assertRaises(NamedPlannerError):
            create_named_execution_plan(question, route, select_playbook(route))
        named = select_named_playbook(route)
        self.assertEqual(named.selected_playbook.playbook_version, "2.0.0")

    def test_six_routed_named_plans_are_ready_and_sql_free(self) -> None:
        cases = (
            ("CMP Cpk 异常", "capability_excursion"),
            ("Nova-P1 最近7天良率下降", "yield_decline"),
            ("CMP-01 最近7天故障", "equipment_fault"),
            ("追踪 LOT-001", "lot_trace"),
            ("CMP SOP 规范", "sop_lookup"),
            ("工厂综合诊断", "fab_diagnostic"),
        )
        for question, intent in cases:
            with self.subTest(intent=intent):
                route = route_question(question, self.current_date)
                plan = create_named_execution_plan(question, route)
                self.assertEqual(
                    (route.intent, plan.route_intent, plan.status),
                    (intent, intent, "ready"),
                )
                self.assertEqual(
                    (plan.schema_version, plan.planner_version), ("1.2", "2.0.0")
                )
                self.assertTrue(
                    all(step.tool != "query_manufacturing_data" for step in plan.steps)
                )
                ids = {step.step_id for step in plan.steps}
                self.assertTrue(all(set(step.depends_on) <= ids for step in plan.steps))
                self.assertEqual(plan.budget.planned_tool_calls, len(plan.steps))

    def test_canonical_nonselected_states_and_forged_selections(self) -> None:
        unsupported_question = "你好"
        unsupported_route = route_question(unsupported_question, self.current_date)
        unsupported = create_named_execution_plan(
            unsupported_question, unsupported_route
        )
        self.assertEqual(unsupported.status, "unsupported")
        ambiguous_question = "CMP 良率和设备故障"
        ambiguous_route = route_question(ambiguous_question, self.current_date)
        ambiguous = create_named_execution_plan(ambiguous_question, ambiguous_route)
        self.assertEqual(ambiguous.status, "clarification_required")
        missing_question = "追踪批次"
        missing_route = route_question(missing_question, self.current_date)
        missing = create_named_execution_plan(missing_question, missing_route)
        self.assertEqual(missing.status, "clarification_required")

        lot_route = route_question("追踪 LOT-001", self.current_date)
        yield_route = route_question("分析良率", self.current_date)
        lot_selection = select_named_playbook(lot_route)
        with self.assertRaises(NamedPlannerError):
            create_named_execution_plan("分析良率", yield_route, lot_selection)
        old = replace(lot_selection.selected_playbook, playbook_version="1.0.0")
        with self.assertRaises(NamedPlannerError):
            create_named_execution_plan(
                "追踪 LOT-001", lot_route, replace(lot_selection, selected_playbook=old)
            )
        with self.assertRaises(NamedPlannerError):
            create_named_execution_plan(
                "追踪 LOT-001",
                lot_route,
                replace(lot_selection, status="unsupported", selected_playbook=None),
            )

    def test_legacy_plan_is_unchanged_by_named_planner(self) -> None:
        question = "追踪 LOT-001"
        route = route_question(question, self.current_date)
        selection = select_playbook(route)
        before = create_execution_plan(question, route, selection).to_dict()
        create_named_execution_plan(question, route)
        after = create_execution_plan(question, route, selection).to_dict()
        self.assertEqual(before, after)
        self.assertIn(
            "query_manufacturing_data", [step["tool"] for step in before["steps"]]
        )


if __name__ == "__main__":
    unittest.main()
