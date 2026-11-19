from datetime import date
from unittest import TestCase

from app.agent_runtime.synthesis.ready import synthesize_duty_lookup
from app.bootstrap.evidence_assembly import validate_evidence
from app.evidence.answer_synthesizer import create_answer_contract, synthesize_submission
from app.evidence.validator import EvidenceObservation
from app.intent_runtime.routing import route_question
from app.planning_runtime.named_playbooks import focus_duty_lookup, select_named_playbook
from app.planning_runtime.service import create_execution_plan


def plan_for(question):
    route = route_question(question, date(2026, 8, 8))
    selection = focus_duty_lookup(question, route, select_named_playbook(route))
    return create_execution_plan(question, route, selection), selection.selected_playbook


class DutyAnswerEvidenceTests(TestCase):
    def test_cpk_lookup_calls_only_the_metric_and_renders_actual_value(self):
        plan, playbook = plan_for("查询 2026-08-07 CMP-02 的 Cpk 是多少")
        self.assertEqual([step.tool for step in plan.steps], ["get_process_capability"])
        step = plan.steps[0]
        call = EvidenceObservation(step.tool, step.parameters, "success", [{
            "equipment_id": "CMP-02", "metric_name": "Thickness", "cpk": 0.92, "samples": 18,
        }], source_ref="TOOL:S01")
        validation = validate_evidence(plan, playbook, [call])
        contract = create_answer_contract(validation)
        answer = synthesize_duty_lookup(validation, contract, [call])
        self.assertIn("Thickness 的 Cpk 为 0.92", answer.answer)
        self.assertIn("2026-08-07", answer.answer)
        self.assertIn("样本 18", answer.answer)
        self.assertEqual(answer.report.source_refs, ("TOOL:S01",))
        self.assertNotIn("allowed_conclusion_strength", validation.to_dict())
        self.assertNotIn("capability_values", contract.to_dict())

    def test_alarm_zero_requires_complete_success(self):
        plan, playbook = plan_for("查询 2026-08-07 CMP-02 有没有报警")
        self.assertEqual([step.tool for step in plan.steps], ["get_equipment_event_timeline"])
        step = plan.steps[0]
        for status, rows, error, expected in (
            ("success", [], None, "范围内记录了 0 条报警"),
            ("success", [{"equipment_id": "CMP-02", "event_type": "PM"}] * 100, None, "无法确认该范围内的报警总数"),
            ("error", None, "timeout", "读取超时"),
            ("blocked", None, None, "当前调用受限"),
        ):
            with self.subTest(status=status, expected=expected):
                arguments = step.parameters if status == "success" else {}
                call = EvidenceObservation(step.tool, arguments, status, rows, error=error, source_ref="TOOL:S01")
                validation = validate_evidence(plan, playbook, [call])
                answer = synthesize_duty_lookup(validation, create_answer_contract(validation), [call])
                self.assertIn(expected, answer.answer)
                if status != "success" or rows:
                    self.assertNotIn("范围内记录了 0 条报警", answer.answer)

    def test_shift_does_not_silently_query_a_different_window(self):
        for question in ("CMP-02 昨晚 Cpk 是多少", "查询昨班 CMP-02 报警次数"):
            with self.subTest(question=question):
                plan, _ = plan_for(question)
                self.assertEqual(plan.status, "clarification_required")
                self.assertEqual(plan.steps, ())
                self.assertTrue(any("全天记录" in item for item in plan.clarification_questions))

    def test_valid_cpk_survives_unrelated_source_failure_and_wrong_readings_are_omitted(self):
        plan, playbook = plan_for("分析 2026-08-07 CMP-02 Cpk 下降与温漂的关系")
        self.assertIn("get_sensor_summary", {step.tool for step in plan.steps})
        cpk, sensor = (
            next(step for step in plan.steps if step.tool == tool)
            for tool in ("get_process_capability", "get_sensor_summary")
        )
        reading = EvidenceObservation(cpk.tool, cpk.parameters, "success", [{
            "equipment_id": "CMP-02", "samples": 38, "mean_value": 100.0, "sigma": 1.82,
            "cpk": 0.92, "metric_name": "Thickness", "metric_unit": "nm",
            "spec_lsl": 95.0, "spec_usl": 105.0, "process_step": "CMP",
        }], source_ref=f"TOOL:{cpk.step_id}")
        for sensor_calls in ([], [
            EvidenceObservation(sensor.tool, sensor.parameters, "error", error="timeout", source_ref=f"TOOL:{sensor.step_id}"),
        ]):
            validation = validate_evidence(plan, playbook, [reading, *sensor_calls])
            contract = create_answer_contract(validation)
            answer = synthesize_submission({
                "analysis_protocol_version": "2.0",
                "facts": [
                    {"statement": statement, "evidence_refs": [reading.source_ref]}
                    for statement in (
                        "CMP-02 Cpk 为 0.92", "CMP-02 Cpk 为 0.29", "CMP-03 Cpk 为 0.92",
                        "CMP-02 Cpk 为 0.92%", "2026-08-05 CMP-02 Cpk 为 0.92",
                    )
                ],
                "conclusion": "当前批次已经放行",
            }, contract)
            self.assertIn("CMP-02 Cpk 为 0.92", answer.answer, answer.report.claim_support)
            for wrong in ("0.29", "CMP-03", "0.92%", "2026-08-05", "已经放行"):
                self.assertNotIn(wrong, answer.answer)
