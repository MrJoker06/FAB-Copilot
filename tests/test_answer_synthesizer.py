from __future__ import annotations

import asyncio
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app import agent as agent_module
from app.answer_synthesizer import (
    REQUIRED_SECTIONS,
    create_answer_contract,
    synthesize_legacy_answer,
    synthesize_submission,
)
from app.domain_playbooks import select_playbook
from app.evidence_validator import EvidenceObservation, validate_evidence
from app.intent_router import route_question
from app.planner import create_execution_plan


def _context(question: str):
    route = route_question(question, current_date=date(2026, 7, 18))
    selection = select_playbook(route)
    plan = create_execution_plan(question, route, selection)
    return selection, plan


def _observation(plan, tool: str, result):
    step = next(item for item in plan.steps if item.tool == tool)
    return EvidenceObservation(tool, dict(step.parameters), "success", result)


def _supported_yield_contract():
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
        _observation(plan, "search_knowledge", [{
            "reference_id": "KB-1", "source_type": "knowledge", "source": "良率分析规范",
            "retrieval": {"confidence": "medium"},
        }]),
    ]
    validation = validate_evidence(plan, selection.selected_playbook, observations)
    sources = [{
        "reference_id": "KB-1", "source_type": "knowledge", "source": "良率分析规范",
        "section": "产品分层", "chunk_id": 1,
    }]
    return create_answer_contract(validation, sources), sources


class AnswerSynthesizerTests(unittest.TestCase):
    def test_structured_submission_renders_all_sections_and_valid_sources(self):
        contract, sources = _supported_yield_contract()
        payload = {
            "conclusion": "当前总体良率下降与 Nova-P1 产品内下降同时出现，但因果关系尚未证明。",
            "facts": [{
                "statement": "最近四周总体良率为 91.2%。",
                "evidence_refs": ["TOOL:get_fab_overview"],
            }],
            "inferences": [{
                "statement": "产品内变化比产品组合变化更值得优先检查。",
                "evidence_refs": ["TOOL:query_manufacturing_data"],
            }],
            "hypotheses": [{
                "statement": "Particle 缺陷可能与下降同期。",
                "evidence_refs": ["TOOL:get_defect_pareto", "KB-1"],
                "verification": "按产品和周次关联缺陷与良率。",
            }],
            "recommendations": [{
                "action": "复核 Nova-P1 同期缺陷批次。",
                "rationale": "产品分层显示该产品需要优先检查。",
                "requires_review": False,
            }],
            "limitations": ["当前分析未证明制程缺陷与良率下降存在因果关系。"],
            "source_refs": ["KB-1"],
        }

        result = synthesize_submission(payload, contract, sources)

        for section in REQUIRED_SECTIONS:
            self.assertIn(f"## {section}", result.answer)
        self.assertIn("[数据 get_fab_overview]", result.answer)
        self.assertIn("[来源 KB-1]", result.answer)
        self.assertEqual(result.report.status, "structured")
        self.assertEqual(result.report.invalid_source_refs, ())
        self.assertEqual(result.report.moved_claims, 0)

    def test_insufficient_evidence_demotes_conclusion_and_unreferenced_facts(self):
        selection, plan = _context("分析 CMP-03 最近7天 Cpk 不合格")
        validation = validate_evidence(plan, selection.selected_playbook, [])
        contract = create_answer_contract(validation)
        payload = {
            "conclusion": "可以确定主要原因是 CMP-03 抛光头老化。",
            "facts": [{"statement": "CMP-03 已经导致全部批次异常。", "evidence_refs": []}],
            "inferences": [],
            "hypotheses": [],
            "recommendations": [],
            "limitations": [],
            "source_refs": [],
        }

        result = synthesize_submission(payload, contract)

        self.assertIn("不能形成诊断性结论", result.answer)
        self.assertIn("## 待验证假设", result.answer)
        self.assertNotIn("## 已确认事实\n- CMP-03", result.answer)
        self.assertGreaterEqual(result.report.moved_claims, 1)
        self.assertTrue(result.report.wording_adjustments)

    def test_invalid_source_is_removed_and_reported(self):
        contract, sources = _supported_yield_contract()
        payload = {
            "conclusion": "当前证据支持方向性判断。",
            "facts": [{
                "statement": "总体良率为 91.2%。 [来源 KB-FAKE]",
                "evidence_refs": ["TOOL:get_fab_overview"],
            }],
            "inferences": [],
            "hypotheses": [],
            "recommendations": [],
            "limitations": [],
            "source_refs": ["KB-FAKE"],
        }

        result = synthesize_submission(payload, contract, sources)

        self.assertNotIn("[来源 KB-FAKE]", result.answer)
        self.assertEqual(result.report.invalid_source_refs, ("KB-FAKE",))

    def test_legacy_answer_is_repaired_only_for_domain_plan(self):
        contract, sources = _supported_yield_contract()
        repaired = synthesize_legacy_answer("模型返回了未分段答案。", contract, sources)

        self.assertEqual(repaired.report.status, "repaired")
        self.assertTrue(all(f"## {section}" in repaired.answer for section in REQUIRED_SECTIONS))

        selection, plan = _context("分析 CMP 划伤缺陷 Pareto")
        validation = validate_evidence(plan, selection.selected_playbook, [])
        generic = synthesize_legacy_answer("保持原样", create_answer_contract(validation))
        self.assertEqual(generic.answer, "保持原样")
        self.assertEqual(generic.report.status, "not_applicable")

    def test_agent_accepts_submit_analysis_and_streams_rendered_answer(self):
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
            submission = {
                "conclusion": "CMP-03 的能力偏低，但当前只能形成待验证假设。",
                "facts": [{
                    "statement": "CMP-03 Cpk 为 1.1。",
                    "evidence_refs": ["TOOL:get_process_capability"],
                }],
                "inferences": [],
                "hypotheses": [{
                    "statement": "均值偏移可能是候选因素。",
                    "evidence_refs": ["TOOL:get_process_capability"],
                    "verification": "补查异常批次和设备传感器。",
                }],
                "recommendations": [],
                "limitations": [],
                "source_refs": [],
            }
            return ({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "submit-call",
                    "type": "function",
                    "function": {"name": "submit_analysis", "arguments": json.dumps(submission)},
                }],
            }, {"total_tokens": 8}, "response-2")

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
        rows = [{
            "equipment_id": "CMP-03", "samples": 120, "mean_value": 100.0, "sigma": 1.0,
            "cpk": 1.1, "metric_name": "Thickness", "metric_unit": "nm",
            "spec_lsl": 95.0, "spec_usl": 105.0,
        }]
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {"get_process_capability": lambda **_: rows}),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "分析 CMP-03 最近7天 Cpk 不合格", [], "run-answer-synthesizer-test", progress,
            ))

        streamed = "".join(event.get("delta", "") for event in events if event.get("event") == "answer_delta")
        self.assertEqual(streamed, result["answer"])
        self.assertEqual(result["answer_synthesis"]["status"], "structured")
        self.assertIn("## 已确认事实", result["answer"])
        self.assertIn("submit_analysis", {tool["function"]["name"] for tool in requests[0]["tools"]})


if __name__ == "__main__":
    unittest.main()
