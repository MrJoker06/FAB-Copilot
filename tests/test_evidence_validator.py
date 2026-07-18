from __future__ import annotations

import asyncio
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app import agent as agent_module
from app.domain_playbooks import select_playbook
from app.evidence_validator import EvidenceObservation, validate_evidence, validator_system_message
from app.intent_router import route_question
from app.planner import create_execution_plan


def _context(question: str):
    route = route_question(question, current_date=date(2026, 7, 18))
    selection = select_playbook(route)
    return selection, create_execution_plan(question, route, selection)


def _observation(plan, tool: str, result, *, occurrence: int = 0, arguments: dict | None = None):
    steps = [step for step in plan.steps if step.tool == tool]
    return EvidenceObservation(
        tool,
        dict(arguments if arguments is not None else steps[occurrence].parameters),
        "success",
        result,
    )


class EvidenceValidatorTests(unittest.TestCase):
    def test_fab_diagnostic_real_reports_cover_all_required_evidence(self):
        question = "关于目前的制造数据你有什么改进建议"
        route = route_question(question, current_date=date(2026, 7, 18))
        selection = select_playbook(route)
        plan = create_execution_plan(question, route, selection)
        observations = [
            EvidenceObservation(
                step.tool,
                step.parameters,
                "success",
                agent_module.TOOL_HANDLERS[step.tool](**step.parameters),
            )
            for step in plan.steps
        ]

        validation = validate_evidence(plan, selection.selected_playbook, observations)

        self.assertEqual(validation.coverage["required_total"], 4)
        self.assertEqual(validation.coverage["required_covered"], 4)
        self.assertEqual(validation.coverage["required_coverage_pct"], 100.0)
        self.assertNotIn(validation.allowed_conclusion_strength, {"insufficient", "hypothesis_only"})

    def test_complete_required_yield_evidence_allows_supported_conclusion(self):
        selection, plan = _context("最近四周良率下降")
        observations = [
            _observation(plan, "get_fab_overview", {
                "start": "2026-06-21", "end": "2026-07-18", "lots": 160,
                "wafers": 4000, "yield_pct": 91.2,
            }),
            _observation(plan, "get_yield_trend", [
                {"period": "2026-25", "week_start": "2026-06-22", "lots": 40, "yield_pct": 92.0},
                {"period": "2026-26", "week_start": "2026-06-29", "lots": 40, "yield_pct": 91.5},
            ]),
            _observation(plan, "query_manufacturing_data", [
                {"product": "Nova-P1", "technology_nm": 28, "lots": 80, "wafers": 2000, "yield_pct": 90.8},
            ]),
            _observation(plan, "get_defect_pareto", [
                {"defect_type": "Particle", "process_steps": "CLEAN,CVD", "defect_count": 120,
                 "affected_lots": 44, "share_pct": 24.0},
            ]),
        ]

        validation = validate_evidence(plan, selection.selected_playbook, observations)

        self.assertEqual(validation.coverage["required_covered"], 3)
        self.assertEqual(validation.coverage["required_coverage_pct"], 100.0)
        self.assertEqual(validation.coverage["field_coverage_pct"], 100.0)
        self.assertEqual(validation.allowed_conclusion_strength, "supported")
        self.assertFalse(validation.causal_claims_allowed)
        self.assertEqual(validation.conflicts, ())
        self.assertEqual(
            {item.evidence_id: item.status for item in validation.evidence_checks},
            {"YLD-01": "covered", "YLD-02": "covered", "YLD-03": "covered", "YLD-04": "optional_missing"},
        )

    def test_scope_mismatch_missing_evidence_and_low_confidence_limit_conclusion(self):
        selection, plan = _context("分析 CMP-03 最近7天 Cpk 不合格")
        capability = _observation(
            plan,
            "get_process_capability",
            [{"equipment_id": "CVD-01", "samples": 100, "cpk": 0.8}],
            arguments={"start": "2026-07-12", "end": "2026-07-18"},
        )
        excursion = _observation(plan, "get_recent_excursions", [{
            "run_time": "2026-07-17T01:00:00", "lot_id": "L1", "process_step": "CMP",
            "equipment_id": "CMP-03", "excursion_code": "CMP-THK-HI", "measurement_name": "Thickness",
            "measurement_value": 106.0, "measurement_unit": "nm", "spec_lsl": 95.0, "spec_usl": 105.0,
        }])
        knowledge = _observation(plan, "search_knowledge", [{
            "reference_id": "KB-1", "source_type": "knowledge", "source": "控制计划", "section": "CMP",
            "retrieval": {"confidence": "low"},
        }])

        validation = validate_evidence(
            plan,
            selection.selected_playbook,
            [capability, excursion, knowledge],
        )

        checks = {item.evidence_id: item.status for item in validation.evidence_checks}
        self.assertEqual(checks["CAP-01"], "missing")
        self.assertEqual(checks["CAP-02"], "covered")
        self.assertEqual(checks["CAP-04"], "covered")
        self.assertEqual(validation.allowed_conclusion_strength, "hypothesis_only")
        self.assertIn("scope_mismatch", {item.code for item in validation.risks})
        self.assertIn("low_source_confidence", {item.code for item in validation.risks})

    def test_small_samples_truncation_and_conflicting_specs_are_reported(self):
        selection, plan = _context("分析 CMP-03 最近7天 Cpk 不合格")
        rows = [
            {
                "equipment_id": "CMP-03", "samples": 12, "mean_value": 100.0, "sigma": 1.0,
                "cpk": 1.1, "metric_name": "Thickness", "metric_unit": "nm",
                "spec_lsl": 95.0, "spec_usl": 105.0,
            },
            {
                "equipment_id": "CMP-03", "samples": 12, "mean_value": 100.0, "sigma": 1.0,
                "cpk": 1.1, "metric_name": "Thickness", "metric_unit": "nm",
                "spec_lsl": 94.0, "spec_usl": 106.0,
            },
        ]
        capability = _observation(plan, "get_process_capability", rows)
        truncated = _observation(
            plan,
            "get_recent_excursions",
            [{"run_time": str(index)} for index in range(100)],
        )

        validation = validate_evidence(plan, selection.selected_playbook, [capability, truncated])

        risk_codes = {item.code for item in validation.risks}
        self.assertIn("small_sample", risk_codes)
        self.assertIn("result_truncated", risk_codes)
        self.assertEqual({item.code for item in validation.conflicts}, {"fact_conflict"})
        self.assertEqual(validation.allowed_conclusion_strength, "hypothesis_only")

    def test_unsupported_plan_is_not_applicable_and_prompt_is_serializable(self):
        selection, plan = _context("分析 CMP 划伤缺陷 Pareto")

        validation = validate_evidence(plan, selection.selected_playbook, [])

        self.assertEqual(validation.status, "not_applicable")
        self.assertEqual(validation.allowed_conclusion_strength, "not_applicable")
        payload = json.loads(validator_system_message(validation).split("evidence_validation=", 1)[1])
        self.assertEqual(payload, validation.to_dict())

    def test_agent_injects_latest_validation_before_synthesis(self):
        requests: list[dict] = []
        events: list[dict] = []
        round_number = 0

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal round_number
            round_number += 1
            requests.append(request_payload)
            if round_number == 1:
                return ({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "capability-call",
                        "type": "function",
                        "function": {
                            "name": "get_process_capability",
                            "arguments": json.dumps({
                                "start": "2026-07-12", "end": "2026-07-18", "process_step": "CMP",
                            }),
                        },
                    }],
                }, {"total_tokens": 5}, "response-1")
            return ({"role": "assistant", "content": "仅形成待验证假设。"}, {"total_tokens": 5}, "response-2")

        async def progress(event: dict) -> None:
            events.append(event)

        settings = SimpleNamespace(
            deepseek_api_key="test-key",
            deepseek_base_url="https://example.test",
            deepseek_model="test-model",
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        capability_rows = [{
            "equipment_id": "CMP-03", "samples": 120, "mean_value": 100.0, "sigma": 1.0,
            "cpk": 1.1, "metric_name": "Thickness", "metric_unit": "nm",
            "spec_lsl": 95.0, "spec_usl": 105.0,
        }]
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"get_process_capability": lambda **_: capability_rows}),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "分析 CMP-03 最近7天 Cpk 不合格",
                [],
                "run-evidence-validator-test",
                progress,
            ))

        self.assertEqual(result["evidence_validation"]["coverage"]["required_covered"], 1)
        self.assertEqual(result["evidence_validation"]["allowed_conclusion_strength"], "hypothesis_only")
        latest_message = next(
            item["content"] for item in reversed(requests[1]["messages"])
            if item["role"] == "system" and "evidence_validation=" in item["content"]
        )
        latest_payload = json.loads(latest_message.split("evidence_validation=", 1)[1])
        self.assertEqual(latest_payload["coverage"]["required_covered"], 1)
        self.assertTrue(any(event.get("stage") == "validation" for event in events))


if __name__ == "__main__":
    unittest.main()
