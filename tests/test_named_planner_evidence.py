from __future__ import annotations

import unittest
from datetime import date

from app.evidence.semantics import descriptor_for_tool
from app.evidence.validator import EvidenceObservation, validate_evidence
from app.intent_runtime.routing import route_question
from app.planning_runtime.named_playbooks import select_named_playbook
from app.planning_runtime.named_planner import create_named_execution_plan


class NamedPlannerEvidenceTests(unittest.TestCase):
    current_date = date(2026, 10, 31)

    def test_named_filter_negative_matrix_does_not_count_as_evidence(self) -> None:
        cases = (
            (
                "Nova-P1 最近7天良率下降",
                "get_product_yield_breakdown",
                {"start": "2026-10-25", "end": "2026-10-31"},
            ),
            (
                "Nova-P1 最近7天良率下降",
                "get_product_yield_breakdown",
                {"start": "2026-10-25", "end": "2026-10-31", "product": "nova-p1"},
            ),
            (
                "CMP-01 最近7天故障",
                "get_equipment_event_timeline",
                {"start": "2026-10-25", "end": "2026-10-31", "equipment_id": "cmp-01"},
            ),
            (
                "CMP-01 最近7天故障",
                "get_equipment_excursion_history",
                {"start": "2026-10-25", "end": "2026-10-31", "equipment_id": "CMP-01"},
            ),
            (
                "CMP-01 最近7天故障",
                "get_equipment_excursion_history",
                {
                    "start": "2026-10-25",
                    "end": "2026-10-31",
                    "process_step": "ETCH",
                    "equipment_id": "CMP-01",
                },
            ),
            ("追踪 LOT-0001-001", "get_lot_identity", {"lot_id": "lot-0001-001"}),
            (
                "追踪 LOT-0001-001",
                "get_lot_identity",
                {"lot_id": "LOT-0001-001", "start": "2026-10-25"},
            ),
        )
        for question, tool, arguments in cases:
            with self.subTest(tool=tool, arguments=arguments):
                route = route_question(question, self.current_date)
                selection = select_named_playbook(route)
                plan = create_named_execution_plan(question, route, selection)
                validation = validate_evidence(
                    plan,
                    selection.selected_playbook,
                    [EvidenceObservation(tool, arguments, "success", [{}])],
                )
                self.assertTrue(
                    any(issue.code == "scope_mismatch" for issue in validation.risks)
                )
                self.assertNotIn(f"TOOL:{tool}", validation.reference_evidence)

    def test_correct_named_arguments_match_and_all_native_semantics_are_literal(
        self,
    ) -> None:
        question = "追踪 LOT-0001-001"
        route = route_question(question, self.current_date)
        selection = select_named_playbook(route)
        plan = create_named_execution_plan(question, route, selection)
        step = next(item for item in plan.steps if item.tool == "get_lot_identity")
        validation = validate_evidence(
            plan,
            selection.selected_playbook,
            [
                EvidenceObservation(
                    step.tool, step.parameters, "success", [{"lot_id": "LOT-0001-001"}]
                )
            ],
        )
        self.assertIn("TOOL:get_lot_identity", validation.reference_evidence)
        self.assertFalse(
            any(issue.code == "scope_mismatch" for issue in validation.risks)
        )

        cases = (
            (
                "get_product_yield_breakdown",
                {"start": "2026-01-01", "end": "2026-01-02", "product": "P1"},
                ("metric", "final_wafer_yield", "product", "fixed_report"),
            ),
            (
                "get_equipment_event_timeline",
                {"start": "2026-01-01", "end": "2026-01-02", "equipment_id": "CMP-01"},
                ("event", "equipment_event", "event", "fixed_report"),
            ),
            (
                "get_equipment_excursion_history",
                {
                    "start": "2026-01-01",
                    "end": "2026-01-02",
                    "process_step": "CMP",
                    "equipment_id": "CMP-01",
                },
                ("event", "process_excursion_record", "event", "fixed_report"),
            ),
            (
                "get_lot_identity",
                {"lot_id": "LOT-001"},
                ("record", "lot_identity", "lot", "fixed_report"),
            ),
            (
                "get_lot_process_history",
                {"lot_id": "LOT-001"},
                ("record", "lot_process_history", "process_run", "fixed_report"),
            ),
            (
                "get_lot_excursion_history",
                {"lot_id": "LOT-001"},
                ("event", "process_excursion_record", "event", "fixed_report"),
            ),
            (
                "get_lot_defect_history",
                {"lot_id": "LOT-001"},
                ("event", "defect_record", "defect_event", "fixed_report"),
            ),
            (
                "get_lot_wafer_map_patterns",
                {"lot_id": "LOT-001"},
                ("record", "wafer_map_pattern", "wafer", "fixed_report"),
            ),
        )
        for tool, arguments, expected in cases:
            with self.subTest(tool=tool):
                descriptor = descriptor_for_tool("TOOL:test", tool, arguments)
                self.assertEqual(
                    (
                        descriptor.kind,
                        descriptor.semantic_id,
                        descriptor.grain,
                        descriptor.filter_provenance,
                    ),
                    expected,
                )
                self.assertEqual(
                    (descriptor.start, descriptor.end),
                    (arguments.get("start"), arguments.get("end")),
                )
                self.assertNotIn("_semantic_template", arguments)


if __name__ == "__main__":
    unittest.main()
