from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime import service as agent_module
from app.evidence.answer_synthesizer import (
    MODEL_KNOWLEDGE_DISCLOSURE,
    MODEL_KNOWLEDGE_REF,
    REQUIRED_SECTIONS,
    SUBMIT_ANALYSIS_TOOL,
    _select_presentation,
    create_answer_contract,
    synthesizer_system_message,
    synthesize_legacy_answer,
    synthesize_submission,
)
from app.manufacturing.playbooks import select_playbook
from app.evidence.validator import EvidenceObservation, validate_evidence
from app.intent_runtime.routing import route_question
from app.planning_runtime.service import create_execution_plan


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


def _structured_claim(contract, reference: str, statement: str, **extra):
    metadata = contract.source_semantics[reference]
    return {
        "statement": statement,
        "evidence_refs": [reference],
        "claim_kind": metadata["kind"],
        "semantic_id": metadata["semantic_id"],
        "scope": metadata["scope"],
        "time_range": {"start": metadata["start"], "end": metadata["end"]},
        "grain": metadata["grain"],
        "claim_role": metadata["scope_role"],
        **extra,
    }


class AnswerSynthesizerTests(unittest.TestCase):
    def test_submit_analysis_schema_accepts_v2_shape_without_legacy_metadata(self):
        properties = SUBMIT_ANALYSIS_TOOL["function"]["parameters"]["properties"]
        self.assertEqual(properties["analysis_protocol_version"]["enum"], ["2.0"])
        self.assertNotIn("required", properties["conclusion_claim"])
        fact_required = properties["facts"]["items"]["required"]
        self.assertEqual(fact_required, ["statement", "evidence_refs", "semantic_id", "scope", "time_range", "claim_role"])
        inference = properties["inferences"]["items"]
        self.assertEqual(inference["required"], ["statement"])
        self.assertTrue({"fact_indices", "basis", "uncertainty", "scope", "time_range", "claim_role"} <= set(inference["properties"]))

    def test_v2_prompt_scopes_conclusion_protocol_separately_from_legacy_metadata(self):
        contract, _ = _supported_yield_contract()
        prompt = synthesizer_system_message(contract)
        self.assertIn("conclusion_claim 必须引用已验证综合推断的 inference_indices", prompt)
        self.assertIn("目标 scope、time_range、claim_role", prompt)
        self.assertIn("仅当省略 analysis_protocol_version、使用旧协议时", prompt)

    def test_model_knowledge_prompt_uses_legacy_fallback_not_v2_manufacturing_protocol(self):
        selection, plan = _context("查询 GaN 与 Si 器件工艺差异 SOP")
        contract = create_answer_contract(
            validate_evidence(plan, selection.selected_playbook, []),
            allow_model_knowledge_fallback=True,
        )
        prompt = synthesizer_system_message(contract)
        self.assertIn("省略 analysis_protocol_version", prompt)
        self.assertIn("不要提交 TOOL:Sxx、fact_indices 或 inference_indices", prompt)
        self.assertNotIn("使用 analysis_protocol_version=2.0", prompt)
        self.assertNotIn("旧协议时，制造域", prompt)

    def test_claim_level_support_keeps_observed_yield_when_root_cause_is_missing(self):
        selection, plan = _context("最近四周良率下降")
        overview = _observation(plan, "get_fab_overview", {
            "start": "2026-06-21", "end": "2026-07-18", "lots": 160,
            "wafers": 4000, "yield_pct": 91.2,
        })
        trend = _observation(plan, "get_yield_trend", [
            {"period": "2026-25", "week_start": "2026-06-22", "lots": 40, "yield_pct": 92.0},
            {"period": "2026-26", "week_start": "2026-06-29", "lots": 40, "yield_pct": 91.5},
        ])
        product = _observation(plan, "query_manufacturing_data", [
            {"product": "Nova-P1", "technology_nm": 28, "lots": 80, "wafers": 2000, "yield_pct": 90.8},
        ])
        missing_cause = _observation(plan, "get_defect_pareto", [])
        validation = validate_evidence(plan, selection.selected_playbook, [overview, trend, product, missing_cause])
        contract = create_answer_contract(validation)
        yield_ref, cause_ref = "TOOL:S02", "TOOL:S04"
        payload = {
            "conclusion": "良率下降已得到当前观测证实。",
            "conclusion_evidence_refs": [yield_ref],
            "conclusion_claim": _structured_claim(contract, yield_ref, "良率下降已得到当前观测证实。"),
            "facts": [_structured_claim(contract, yield_ref, "当前总体良率为 91.2%。")],
            "inferences": [_structured_claim(contract, cause_ref, "缺陷记录足以解释良率下降。")],
            "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [],
        }

        result = synthesize_submission(payload, replace(contract, presentation="report"))

        self.assertIn("良率下降已得到当前观测证实", result.answer)
        self.assertIn("当前总体良率为 91.2%", result.answer)
        self.assertIn("缺陷记录足以解释良率下降", result.answer)
        support = {(item["category"], item["statement"]): item["support"] for item in result.report.claim_support}
        self.assertEqual(support[("conclusion", "良率下降已得到当前观测证实。")], "supported")
        self.assertEqual(support[("inference", "缺陷记录足以解释良率下降。")], "unsupported")

    def test_invalid_or_conflicted_reference_cannot_become_confirmed_fact(self):
        contract, sources = _supported_yield_contract()
        ref = "TOOL:S01"
        conflicted = replace(contract, reference_evidence={
            **(contract.reference_evidence or {}),
            ref: {
                "evidence_ids": ("YLD-01",), "statuses": {"YLD-01": "covered"},
                "risk_codes": (), "critical_risk_codes": (), "conflict_codes": ("fact_conflict",),
            },
        })
        payload = {
            "conclusion": "当前良率需要复核。", "conclusion_evidence_refs": [ref],
            "conclusion_claim": _structured_claim(conflicted, ref, "当前良率需要复核。"),
            "facts": [
                _structured_claim(conflicted, ref, "冲突的良率事实。"),
                {**_structured_claim(conflicted, ref, "混合引用的良率事实。"), "evidence_refs": [ref, "BAD-REF"]},
            ],
            "inferences": [], "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [],
        }

        result = synthesize_submission(payload, conflicted, sources)

        self.assertNotIn("## 已确认事实\n- 冲突的良率事实", result.answer)
        self.assertIn("冲突的良率事实", result.answer)
        self.assertIn("当前证据未能验证模型提交的结论", result.answer)
        self.assertNotIn("没有以一致范围支持", result.answer)
        self.assertEqual(result.report.invalid_source_refs, ("BAD-REF",))
        facts = [item for item in result.report.claim_support if item["category"] == "fact"]
        self.assertTrue(all(item["support"] == "unsupported" for item in facts))

    def test_partial_and_structured_mismatch_are_audited_as_unsupported(self):
        selection, plan = _context("最近四周良率下降")
        overview = _observation(plan, "get_fab_overview", {
            "start": "2026-06-21", "end": "2026-07-18", "lots": 160,
            "wafers": 4000, "yield_pct": 91.2,
        })
        contract = create_answer_contract(validate_evidence(plan, selection.selected_playbook, [overview]))
        ref = "TOOL:S01"
        invalid_time = _structured_claim(contract, ref, "范围或时间错误的声明。")
        invalid_time["time_range"] = {"start": "2020-01-01", "end": "2020-01-02"}
        payload = {
            "conclusion": "部分证据支持该结论。", "conclusion_evidence_refs": [ref],
            "conclusion_claim": _structured_claim(contract, ref, "部分证据支持该结论。"),
            "facts": [_structured_claim(contract, ref, "字段不完整的良率事实。"), invalid_time],
            "inferences": [], "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [],
        }

        result = synthesize_submission(payload, contract)

        self.assertNotIn("事实：字段不完整的良率事实", result.answer)
        facts = [item for item in result.report.claim_support if item["category"] == "fact"]
        self.assertTrue(all(item["support"] == "unsupported" for item in facts))
        self.assertTrue(any("字段不完整" in "".join(item["reasons"]) for item in facts))
        self.assertTrue(any("结构化语义" in "".join(item["reasons"]) for item in facts))

    def test_mixed_valid_and_invalid_reference_fails_without_other_conflict(self):
        contract, sources = _supported_yield_contract()
        ref = "TOOL:S01"
        claim = _structured_claim(contract, ref, "混合引用不能确认为事实。")
        claim["evidence_refs"] = [ref, "BAD-REF"]
        payload = {
            "conclusion": "当前观测需要复核。", "conclusion_evidence_refs": [ref],
            "conclusion_claim": _structured_claim(contract, ref, "当前观测需要复核。"),
            "facts": [claim], "inferences": [], "hypotheses": [], "recommendations": [],
            "limitations": [], "source_refs": [],
        }

        result = synthesize_submission(payload, contract, sources)

        fact = next(item for item in result.report.claim_support if item["category"] == "fact")
        self.assertEqual(fact["support"], "unsupported")
        self.assertIn("未许可引用", "".join(fact["reasons"]))
        self.assertEqual(result.report.invalid_source_refs, ("BAD-REF",))

    def test_real_conflict_only_demotes_claims_that_depend_on_conflicted_evidence(self):
        selection, plan = _context("分析 CMP-03 最近7天 Cpk 不合格")
        capability = _observation(plan, "get_process_capability", [
            {"equipment_id": "CMP-03", "samples": 80, "mean_value": 100.0, "sigma": 1.0,
             "cpk": 1.1, "metric_name": "Thickness", "metric_unit": "nm", "spec_lsl": 95.0, "spec_usl": 105.0},
            {"equipment_id": "CMP-03", "samples": 80, "mean_value": 100.0, "sigma": 1.0,
             "cpk": 1.1, "metric_name": "Thickness", "metric_unit": "nm", "spec_lsl": 94.0, "spec_usl": 106.0},
        ])
        excursions = _observation(plan, "get_recent_excursions", [{
            "run_time": "2026-07-17", "lot_id": "L-1", "process_step": "CMP", "equipment_id": "CMP-03",
            "excursion_code": "E-1", "measurement_name": "ScratchCount", "measurement_value": 99.0,
            "measurement_unit": "nm", "spec_lsl": 95.0, "spec_usl": 105.0,
        }])
        contract = create_answer_contract(validate_evidence(plan, selection.selected_playbook, [capability, excursions]))
        payload = {
            "conclusion": "异常记录需要进一步复核。", "conclusion_evidence_refs": ["TOOL:S02"],
            "conclusion_claim": _structured_claim(contract, "TOOL:S02", "异常记录需要进一步复核。"),
            "facts": [
                _structured_claim(contract, "TOOL:S01", "冲突规格下的 Cpk 为 1.1。"),
                _structured_claim(contract, "TOOL:S02", "CMP-03 存在已记录异常。"),
            ],
            "inferences": [], "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [],
        }

        result = synthesize_submission(payload, contract, status="structured")

        support = {item["statement"]: item["support"] for item in result.report.claim_support if item["category"] == "fact"}
        self.assertEqual(support["冲突规格下的 Cpk 为 1.1。"], "unsupported")
        self.assertEqual(support["CMP-03 存在已记录异常。"], "supported")
        self.assertIn("CMP-03 存在已记录异常", result.answer)

    def test_v2_direct_facts_fill_only_known_metadata_and_composite_derives_refs(self):
        contract, _ = _supported_yield_contract()
        scope = {"equipment_ids": ("EQ-1",)}
        semantics = {
            ref: {
                "kind": "metric", "semantic_id": semantic, "grain": "equipment_signal",
                "scope": scope, "start": "2026-07-01", "end": "2026-07-07",
                "filter_provenance": "fixed_report", "scope_role": role,
            }
            for ref, semantic, role in (
                ("TOOL:S01", "equipment_alarm_count", "primary"),
                ("TOOL:S02", "equipment_throughput", "primary"),
                ("TOOL:S03", "equipment_alarm_count", "context_only"),
            )
        }
        evidence = {
            ref: {"statuses": {"E-1": "covered"}, "risk_codes": (), "critical_risk_codes": (), "conflict_codes": ()}
            for ref in semantics
        }
        contract = replace(
            contract, primary_scope_type="equipment", primary_scope_labels=("EQ-1",),
            permitted_source_refs=tuple(semantics), source_semantics=semantics,
            source_scope_roles={ref: item["scope_role"] for ref, item in semantics.items()},
            reference_evidence=evidence,
        )
        fact = lambda statement, ref, semantic: {
            "statement": statement, "evidence_refs": [ref], "semantic_id": semantic,
            "scope": scope, "time_range": {"start": "2026-07-01", "end": "2026-07-07"},
            "claim_role": "primary",
        }
        payload = {
            "analysis_protocol_version": "2.0", "conclusion": "EQ-1 需要优先检查设备稳定性。",
            "conclusion_evidence_refs": [], "conclusion_claim": {
                "inference_indices": [0], "scope": scope,
                "time_range": {"start": "2026-07-01", "end": "2026-07-07"}, "claim_role": "primary",
            },
            "facts": [
                fact("告警增加。", "TOOL:S01", "equipment_alarm_count"),
                fact("吞吐下降。", "TOOL:S02", "equipment_throughput"),
            ],
            "inferences": [{
                "statement": "应优先排查设备稳定性。", "fact_indices": [0, 1],
                "basis": "告警增加与吞吐下降在同一设备和时间窗内同时出现。",
                "uncertainty": "这仅支持排查优先级，不证明根因。",
                "scope": scope, "time_range": {"start": "2026-07-01", "end": "2026-07-07"},
                "claim_role": "primary",
            }],
            "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [],
        }

        result = synthesize_submission(payload, contract)

        inference = next(item for item in result.report.claim_support if item["category"] == "inference")
        self.assertEqual(inference["support"], "supported")
        self.assertEqual(inference["evidence_refs"], ("TOOL:S01", "TOOL:S02"))
        self.assertEqual(result.report.analysis_protocol_version, "2.0")
        self.assertEqual(result.report.schema_version, "1.2")
        self.assertIn("不确定性：这仅支持排查优先级", result.answer)
        self.assertNotIn("claim_kind", result.answer)

        wrong_scope = {**payload, "inferences": [{
            **payload["inferences"][0], "scope": {"equipment_ids": ("EQ-2",)},
        }]}
        rejected_scope = synthesize_submission(wrong_scope, contract)
        scope_support = next(item for item in rejected_scope.report.claim_support if item["category"] == "inference")
        self.assertEqual(scope_support["support"], "unsupported")
        self.assertIn("目标范围", "".join(scope_support["reasons"]))

        wrong_indices = {**payload, "inferences": [{
            **payload["inferences"][0], "fact_indices": [0, 1, "bad"],
        }]}
        rejected_indices = synthesize_submission(wrong_indices, contract)
        index_support = next(item for item in rejected_indices.report.claim_support if item["category"] == "inference")
        self.assertEqual(index_support["support"], "unsupported")
        self.assertIn("整数数组", "".join(index_support["reasons"]))

        wrong_conclusion_scope = {**payload, "conclusion_claim": {
            **payload["conclusion_claim"], "scope": {"equipment_ids": ("EQ-2",)},
        }}
        rejected_conclusion_scope = synthesize_submission(wrong_conclusion_scope, contract)
        conclusion_scope_support = next(item for item in rejected_conclusion_scope.report.claim_support if item["category"] == "conclusion")
        self.assertEqual(conclusion_scope_support["support"], "unsupported")
        self.assertIn("范围", "".join(conclusion_scope_support["reasons"]))

        invalid_conclusion_ref = {**payload, "conclusion_evidence_refs": ["BAD-REF"]}
        rejected_conclusion_ref = synthesize_submission(invalid_conclusion_ref, contract)
        conclusion_ref_support = next(item for item in rejected_conclusion_ref.report.claim_support if item["category"] == "conclusion")
        self.assertEqual(conclusion_ref_support["support"], "unsupported")
        self.assertIn("未许可", "".join(conclusion_ref_support["reasons"]))

        unknown_protocol = {**payload, "analysis_protocol_version": "99.0"}
        rejected_protocol = synthesize_submission(unknown_protocol, contract)
        conclusion = next(item for item in rejected_protocol.report.claim_support if item["category"] == "conclusion")
        self.assertEqual(conclusion["support"], "unsupported")
        self.assertIn("不支持", "".join(conclusion["reasons"]))

        incompatible = {**payload, "facts": [
            fact("告警增加。", "TOOL:S01", "equipment_alarm_count"),
            fact("背景告警。", "TOOL:S03", "equipment_alarm_count"),
        ]}
        rejected = synthesize_submission(incompatible, contract)
        support = next(item for item in rejected.report.claim_support if item["category"] == "inference")
        self.assertEqual(support["support"], "unsupported")
        self.assertIn("未验证", "".join(support["reasons"]))

    def test_clause_level_causal_assessment_preserves_caution_and_rejects_assertions(self):
        contract, _ = _supported_yield_contract()
        contract = replace(contract, causal_claims_allowed=False)
        reference = "TOOL:S01"

        for statement in (
            "当前数据不能证明设备漂移导致良率下降。",
            "是否由设备漂移导致良率下降仍需验证？",
            "设备漂移可能导致良率下降，仍需受控对照。",
        ):
            payload = {
                "conclusion": statement, "conclusion_evidence_refs": [reference],
                "conclusion_claim": _structured_claim(contract, reference, statement),
                "facts": [], "inferences": [], "hypotheses": [], "recommendations": [],
                "limitations": [], "source_refs": [],
            }
            result = synthesize_submission(payload, contract)
            conclusion = next(item for item in result.report.claim_support if item["category"] == "conclusion")
            self.assertEqual(conclusion["support"], "supported", statement)
            self.assertIn(statement, result.answer)

        for statement in (
            "设备漂移是良率下降的根因。",
            "问题出在设备漂移。",
            "良率下降由设备漂移引起。",
            "良率下降源于设备漂移。",
            "当前数据不能证明设备漂移导致良率下降。但是问题出在设备漂移。",
            "不能证明设备漂移导致良率下降，设备漂移造成良率下降。",
            "是否由设备漂移导致良率下降，设备漂移是根因。",
        ):
            payload = {
                "conclusion": statement, "conclusion_evidence_refs": [reference],
                "conclusion_claim": _structured_claim(contract, reference, statement),
                "facts": [], "inferences": [], "hypotheses": [], "recommendations": [],
                "limitations": [], "source_refs": [],
            }
            result = synthesize_submission(payload, contract)
            conclusion = next(item for item in result.report.claim_support if item["category"] == "conclusion")
            self.assertEqual(conclusion["support"], "unsupported", statement)
            self.assertIn("当前证据未能验证模型提交的结论", result.answer)

        for statement in ("是否存在设备漂移？", "设备漂移可能是主因。"):
            fact_payload = {
                "conclusion": "当前记录需要复核。", "conclusion_evidence_refs": [reference],
                "conclusion_claim": _structured_claim(contract, reference, "当前记录需要复核。"),
                "facts": [_structured_claim(contract, reference, statement)],
                "inferences": [], "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [],
            }
            fact_result = synthesize_submission(fact_payload, contract)
            fact = next(item for item in fact_result.report.claim_support if item["category"] == "fact")
            self.assertEqual(fact["support"], "unsupported", statement)
            self.assertIn("直接事实不能使用", "".join(fact["reasons"]))

        definitive_contract = replace(contract, causal_claims_allowed=True, allowed_conclusion_strength="hypothesis_only")
        definitive_payload = {
            "conclusion": "可以确定主要原因是设备漂移。", "conclusion_evidence_refs": [reference],
            "conclusion_claim": _structured_claim(definitive_contract, reference, "可以确定主要原因是设备漂移。"),
            "facts": [], "inferences": [], "hypotheses": [], "recommendations": [],
            "limitations": [], "source_refs": [],
        }
        definitive_result = synthesize_submission(definitive_payload, definitive_contract)
        definitive = next(item for item in definitive_result.report.claim_support if item["category"] == "conclusion")
        self.assertEqual(definitive["support"], "unsupported")

        trend_reference = "TOOL:S02"
        observed_payload = {
            "conclusion": "当前趋势数据已经证实良率下降。", "conclusion_evidence_refs": [trend_reference],
            "conclusion_claim": _structured_claim(definitive_contract, trend_reference, "当前趋势数据已经证实良率下降。"),
            "facts": [_structured_claim(definitive_contract, trend_reference, "当前趋势数据已经证实良率下降。")],
            "inferences": [], "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [],
        }
        observed_result = synthesize_submission(observed_payload, definitive_contract)
        observed_support = {
            item["category"]: item["support"] for item in observed_result.report.claim_support
            if item["category"] in {"conclusion", "fact"}
        }
        self.assertEqual(observed_support, {"conclusion": "supported", "fact": "supported"})

        diagnosis_payload = {
            "conclusion": "当前数据已经证实设备漂移是根因。", "conclusion_evidence_refs": [reference],
            "conclusion_claim": _structured_claim(definitive_contract, reference, "当前数据已经证实设备漂移是根因。"),
            "facts": [], "inferences": [], "hypotheses": [], "recommendations": [],
            "limitations": [], "source_refs": [],
        }
        diagnosis_result = synthesize_submission(diagnosis_payload, definitive_contract)
        diagnosis = next(item for item in diagnosis_result.report.claim_support if item["category"] == "conclusion")
        self.assertEqual(diagnosis["support"], "unsupported")

    def test_v2_hypothetical_causal_inference_is_demoted_and_model_mechanism_is_retained(self):
        contract, _ = _supported_yield_contract()
        scope = {"equipment_ids": ("EQ-1",)}
        semantics = {
            ref: {
                "kind": "metric", "semantic_id": semantic, "grain": "equipment_signal",
                "scope": scope, "start": "2026-07-01", "end": "2026-07-07",
                "filter_provenance": "fixed_report", "scope_role": "primary",
            }
            for ref, semantic in (
                ("TOOL:S01", "equipment_alarm_count"),
                ("TOOL:S02", "equipment_throughput"),
            )
        }
        contract = replace(
            contract, causal_claims_allowed=False, primary_scope_type="equipment",
            primary_scope_labels=("EQ-1",), permitted_source_refs=tuple(semantics),
            source_semantics=semantics, source_scope_roles={ref: "primary" for ref in semantics},
            reference_evidence={
                ref: {"statuses": {"E-1": "covered"}, "risk_codes": (), "critical_risk_codes": (), "conflict_codes": ()}
                for ref in semantics
            },
        )
        fact = lambda statement, ref, semantic: {
            "statement": statement, "evidence_refs": [ref], "semantic_id": semantic,
            "scope": scope, "time_range": {"start": "2026-07-01", "end": "2026-07-07"}, "claim_role": "primary",
        }
        payload = {
            "analysis_protocol_version": "2.0", "conclusion": "是否由告警增加导致吞吐下降仍需验证？",
            "conclusion_evidence_refs": [], "conclusion_claim": {
                "inference_indices": [0], "scope": scope,
                "time_range": {"start": "2026-07-01", "end": "2026-07-07"}, "claim_role": "primary",
            },
            "facts": [
                fact("告警增加。", "TOOL:S01", "equipment_alarm_count"),
                fact("吞吐下降。", "TOOL:S02", "equipment_throughput"),
            ],
            "inferences": [{
                "statement": "是否由告警增加导致吞吐下降仍需验证？", "fact_indices": [0, 1],
                "basis": "两项观测在同一设备和时间窗内出现。", "uncertainty": "尚未进行受控对照。",
                "scope": scope, "time_range": {"start": "2026-07-01", "end": "2026-07-07"}, "claim_role": "primary",
            }],
            "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [],
        }
        result = synthesize_submission(payload, contract)
        inference = next(item for item in result.report.claim_support if item["category"] == "inference")
        conclusion = next(item for item in result.report.claim_support if item["category"] == "conclusion")
        self.assertEqual(inference["support"], "unsupported")
        self.assertIn("待验证内容", "".join(inference["reasons"]))
        self.assertEqual(conclusion["support"], "unsupported")

        selection, plan = _context("查询 GaN 与 Si 器件工艺差异 SOP")
        knowledge_contract = create_answer_contract(
            validate_evidence(plan, selection.selected_playbook, []), allow_model_knowledge_fallback=True,
        )
        for generic_statement in ("通常，温度升高会导致扩散速度增加。", "通常温度变化会导致晶圆应力增加。"):
            knowledge_payload = {
                "conclusion": "以下为一般技术机理说明。", "conclusion_evidence_refs": [MODEL_KNOWLEDGE_REF],
                "facts": [], "inferences": [{
                    "statement": generic_statement, "evidence_refs": [MODEL_KNOWLEDGE_REF],
                }],
                "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [MODEL_KNOWLEDGE_REF],
            }
            knowledge_result = synthesize_submission(knowledge_payload, knowledge_contract)
            knowledge_inference = next(item for item in knowledge_result.report.claim_support if item["category"] == "inference")
            self.assertEqual(knowledge_inference["support"], "supported", generic_statement)
            self.assertIn(generic_statement, knowledge_result.answer)

        production_payload = {
            **knowledge_payload,
            "inferences": [{
                "statement": "一般而言，当前 CMP-03 漂移导致良率下降。",
                "evidence_refs": [MODEL_KNOWLEDGE_REF],
            }],
        }
        production_result = synthesize_submission(production_payload, knowledge_contract)
        production = next(item for item in production_result.report.claim_support if item["category"] == "inference")
        self.assertEqual(production["support"], "unsupported")
        self.assertIn("待验证内容：一般而言，当前 CMP-03 漂移导致良率下降。 [模型通用知识]", production_result.answer)
        self.assertNotIn("模型通用知识：一般而言，当前 CMP-03 漂移导致良率下降。", production_result.answer)

    def test_presentation_selection_obeys_current_request(self):
        contract, _ = _supported_yield_contract()
        self.assertEqual(replace(contract, presentation="brief").presentation, "brief")
        self.assertEqual(_select_presentation("与前天比较，用表格"), "table")
        self.assertEqual(_select_presentation("一句话总结良率"), "brief")
        self.assertEqual(_select_presentation("输出完整诊断报告"), "report")
        self.assertEqual(_select_presentation("一句话总结", "请用表格比较"), "brief")
        self.assertEqual(_select_presentation("继续分析", "请用表格比较"), "table")

    def test_brief_and_table_keep_evidence_limits(self):
        contract, sources = _supported_yield_contract()
        payload = {
            "conclusion": "当前证据支持方向性判断。",
            "conclusion_evidence_refs": ["TOOL:get_fab_overview"],
            "facts": [
                {"statement": "第一条证据。", "evidence_refs": ["TOOL:get_fab_overview"]},
                {"statement": "第二条证据。", "evidence_refs": ["TOOL:get_yield_trend"]},
            ],
            "inferences": [], "hypotheses": [], "recommendations": [],
            "limitations": ["比较范围需要进一步复核。"], "source_refs": ["KB-1"],
        }
        brief = synthesize_submission(payload, replace(contract, presentation="brief"), sources)
        table = synthesize_submission(payload, replace(contract, presentation="table"), sources)
        self.assertIn("证据限制：", brief.answer)
        self.assertIn("比较范围需要进一步复核", brief.answer)
        self.assertIn("第一条证据", brief.answer)
        self.assertIn("第二条证据", brief.answer)
        self.assertIn("| 类型 | 内容 |", table.answer)
        self.assertEqual(brief.report.source_refs, table.report.source_refs)

    def test_compact_has_no_empty_placeholders_or_report_headings(self):
        contract, sources = _supported_yield_contract()
        payload = {
            "conclusion": "当前证据支持方向性判断。", "conclusion_evidence_refs": [],
            "facts": [], "inferences": [], "hypotheses": [], "recommendations": [],
            "limitations": [], "source_refs": [],
        }
        result = synthesize_submission(payload, replace(contract, presentation="compact"), sources)
        self.assertNotIn("## ", result.answer)
        self.assertNotIn("未识别到额外证据限制", result.answer)
        self.assertIn("结论", result.report.sections)

    def test_table_escapes_claim_content(self):
        contract, sources = _supported_yield_contract()
        payload = {
            "conclusion": "A | B\n下一行", "conclusion_evidence_refs": [],
            "facts": [], "inferences": [], "hypotheses": [], "recommendations": [],
            "limitations": [], "source_refs": [],
        }
        result = synthesize_submission(payload, replace(contract, presentation="table"), sources)
        self.assertIn("A \\| B 下一行", result.answer)

    def test_model_knowledge_brief_and_table_keep_all_retained_content(self):
        selection, plan = _context("查询 GaN 与 Si 器件工艺差异 SOP")
        validation = validate_evidence(plan, selection.selected_playbook, [])
        contract = create_answer_contract(validation, allow_model_knowledge_fallback=True)
        payload = {
            "conclusion": "一般技术说明。", "conclusion_evidence_refs": [MODEL_KNOWLEDGE_REF],
            "facts": [],
            "inferences": [{"statement": "知识 | 内容", "evidence_refs": [MODEL_KNOWLEDGE_REF]}],
            "hypotheses": [{"statement": "待验证\n内容", "evidence_refs": ["BAD"], "verification": "复核"}],
            "recommendations": [{"action": "采取复核", "rationale": "降低风险", "requires_review": False}],
            "limitations": [], "source_refs": [MODEL_KNOWLEDGE_REF],
        }
        brief = synthesize_submission(payload, replace(contract, presentation="brief"))
        table = synthesize_submission(payload, replace(contract, presentation="table"))
        for text in (brief.answer, table.answer):
            self.assertIn("知识", text)
            self.assertIn("待验证", text)
            self.assertIn("采取复核", text)
            self.assertIn(MODEL_KNOWLEDGE_DISCLOSURE, text)
        self.assertIn("知识 \\| 内容", table.answer)

    def test_not_applicable_ignores_presentation_without_regression(self):
        selection, plan = _context("你好")
        contract = create_answer_contract(validate_evidence(plan, selection.selected_playbook, []), question="请用表格")
        result = synthesize_submission({"conclusion": "普通回答"}, contract)
        self.assertEqual((result.answer, result.report.status, result.report.sections), ("普通回答", "not_applicable", ()))

    def test_manufacturing_claim_without_structured_contract_is_demoted_without_name_matching(self):
        contract, sources = _supported_yield_contract()
        payload = {
            "conclusion": "当前局部指标需要优先处置。",
            "conclusion_evidence_refs": ["TOOL:get_fab_overview"],
            "facts": [{"statement": "当前局部指标为 91.2%。", "evidence_refs": ["TOOL:get_fab_overview"]}],
            "inferences": [], "hypotheses": [], "recommendations": [], "limitations": [], "source_refs": [],
        }
        result = synthesize_submission(payload, replace(contract, presentation="report"), sources)
        self.assertNotIn("## 已确认事实\n- 当前局部指标为 91.2%", result.answer)
        self.assertIn("当前证据未能验证模型提交的结论", result.answer)

    def test_structured_submission_omits_empty_sections_and_keeps_valid_sources(self):
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

        result = synthesize_submission(payload, replace(contract, presentation="report"), sources)

        self.assertIn("## 结论", result.answer)
        self.assertIn("## 待验证假设", result.answer)
        self.assertIn("## 建议", result.answer)
        self.assertNotIn("当前没有", result.answer)
        self.assertIn("[数据 get_fab_overview]", result.answer)
        self.assertIn("[来源 KB-1]", result.answer)
        self.assertNotIn("## 来源", result.answer)
        self.assertEqual(result.report.status, "structured")
        self.assertEqual(result.report.invalid_source_refs, ())
        self.assertGreaterEqual(result.report.moved_claims, 0)

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
        self.assertIn("待验证：", result.answer)
        self.assertNotIn("## 已确认事实\n- CMP-03", result.answer)
        self.assertGreaterEqual(result.report.moved_claims, 1)
        self.assertTrue(result.report.wording_adjustments)

    def test_empty_knowledge_search_allows_disclosed_model_knowledge(self):
        selection, plan = _context("查询 GaN 与 Si 器件工艺差异 SOP")
        empty_search = _observation(plan, "search_knowledge", [])
        validation = validate_evidence(plan, selection.selected_playbook, [empty_search])
        contract = create_answer_contract(
            validation,
            allow_model_knowledge_fallback=True,
        )
        payload = {
            "conclusion": "GaN 与 Si 器件的主要差异来自材料特性和器件结构。",
            "facts": [],
            "inferences": [{
                "statement": "GaN 的宽禁带和高击穿场强通常更适合高压、高频功率器件。",
                "evidence_refs": [MODEL_KNOWLEDGE_REF],
            }],
            "hypotheses": [],
            "recommendations": [],
            "limitations": [],
            "source_refs": [MODEL_KNOWLEDGE_REF],
        }

        result = synthesize_submission(payload, contract)

        self.assertTrue(contract.model_knowledge_fallback)
        self.assertIn(MODEL_KNOWLEDGE_DISCLOSURE, result.answer)
        self.assertIn("GaN 的宽禁带", result.answer)
        self.assertIn("模型通用知识：", result.answer)
        self.assertIn("[模型通用知识]", result.answer)
        self.assertNotIn("## 来源", result.answer)
        self.assertNotIn("不能形成诊断性结论", result.answer)
        self.assertNotIn("缺少字段", result.answer)

    def test_model_knowledge_fact_is_audited_as_downgraded_inference(self):
        selection, plan = _context("查询 GaN 与 Si 器件工艺差异 SOP")
        contract = create_answer_contract(
            validate_evidence(plan, selection.selected_playbook, []),
            allow_model_knowledge_fallback=True,
        )
        payload = {
            "conclusion": "一般技术说明。", "conclusion_evidence_refs": [MODEL_KNOWLEDGE_REF],
            "facts": [{"statement": "GaN 通常适合高压应用。", "evidence_refs": []}],
            "inferences": [], "hypotheses": [], "recommendations": [], "limitations": [],
            "source_refs": [MODEL_KNOWLEDGE_REF],
        }

        result = synthesize_submission(payload, contract)

        fact = next(item for item in result.report.claim_support if item["category"] == "fact")
        self.assertEqual(fact["support"], "unsupported")
        self.assertIn("不能确认厂内事实", "".join(fact["reasons"]))
        self.assertIn("GaN 通常适合高压应用", result.answer)
        self.assertIn("[模型通用知识]", result.answer)

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

    def test_process_claim_cannot_use_fab_context_as_primary_scope_evidence(self):
        selection, plan = _context("分析最近一周刻蚀机台状况")
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
        contract = create_answer_contract(validation)
        payload = {
            "conclusion": "刻蚀良率为 90%。",
            "conclusion_evidence_refs": ["TOOL:get_fab_overview"],
            "facts": [
                {
                    "statement": "刻蚀良率为 90%。",
                    "evidence_refs": ["TOOL:get_fab_overview"],
                },
                {
                    "statement": "整厂良率为 90%。",
                    "evidence_refs": ["TOOL:get_fab_overview"],
                },
            ],
            "inferences": [],
            "hypotheses": [],
            "recommendations": [],
            "limitations": [],
            "source_refs": [],
        }

        result = synthesize_submission(payload, contract)

        self.assertIn("当前证据未能验证模型提交的结论", result.answer)
        self.assertNotIn("## 已确认事实\n- 整厂良率为 90%", result.answer)
        self.assertNotIn("## 已确认事实\n- 刻蚀良率为 90%", result.answer)
        self.assertIn("范围证据不匹配", " ".join(result.report.wording_adjustments))

    def test_legacy_answer_is_repaired_only_for_domain_plan(self):
        contract, sources = _supported_yield_contract()
        repaired = synthesize_legacy_answer("模型返回了未分段答案。", contract, sources)

        self.assertEqual(repaired.report.status, "repaired")
        self.assertIn("证据限制：", repaired.answer)

        selection, plan = _context("分析 CMP 划伤缺陷 Pareto")
        validation = validate_evidence(plan, selection.selected_playbook, [])
        generic = synthesize_legacy_answer("保持原样", create_answer_contract(validation))
        self.assertEqual(generic.answer, "保持原样")
        self.assertEqual(generic.report.status, "not_applicable")

    def test_agent_accepts_submit_analysis_and_streams_rendered_answer(self):
        requests: list[dict] = []
        events: list[dict] = []

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            requests.append(request_payload)
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
                "time_range": (
                    {"start": semantic["start"], "end": semantic["end"]}
                    if semantic["start"] or semantic["end"] else {}
                ),
                "claim_role": semantic["scope_role"],
            }
            submission = {
                "conclusion": "CMP-03 的能力偏低，但当前只能形成待验证假设。",
                "conclusion_evidence_refs": [reference],
                "conclusion_claim": claim,
                "facts": [{
                    "statement": "CMP-03 Cpk 为 1.1。",
                    "evidence_refs": [reference],
                    **claim,
                }],
                "inferences": [],
                "hypotheses": [],
                "recommendations": [],
                "limitations": [],
                "source_refs": [reference],
            }
            return ({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "submit-call",
                    "type": "function",
                    "function": {"name": "submit_analysis", "arguments": json.dumps(submission)},
                }],
            }, {"total_tokens": 8}, "response-1")

        async def progress(event: dict) -> None:
            events.append(event)

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
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
            patch("app.agent_runtime.service.get_settings", return_value=settings),
            patch("app.agent_runtime.service._stream_completion", new=fake_stream),
            patch.dict(agent_module.TOOL_HANDLERS, {
                "get_process_capability": lambda **_: rows,
                "get_recent_excursions": lambda **_: [],
                "get_sensor_summary": lambda **_: [],
                "search_knowledge": lambda **_: [],
            }),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "分析 CMP-03 最近7天 Cpk 不合格", [], "run-answer-synthesizer-test", progress,
            ))

        streamed = "".join(event.get("delta", "") for event in events if event.get("event") == "answer_delta")
        self.assertEqual(streamed, result["answer"])
        self.assertEqual(result["answer_synthesis"]["status"], "structured")
        self.assertIn("待验证：", result["answer"])
        self.assertIn("submit_analysis", {tool["function"]["name"] for tool in requests[0]["tools"]})
        prompt_contract = next(
            json.loads(item["content"].split("answer_contract=", 1)[1])
            for item in requests[0]["messages"]
            if item["role"] == "system" and "answer_contract=" in item["content"]
        )
        self.assertEqual(prompt_contract["presentation"], "compact")
        self.assertEqual(len(requests), 1)
        self.assertEqual(result["model_tool_selection_calls"], 0)

    def test_agent_attempts_at_most_one_synthesis_only_repair_for_incomplete_submission(self):
        requests: list[dict] = []
        events: list[dict] = []
        round_number = 0

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            nonlocal round_number
            round_number += 1
            requests.append(request_payload)
            arguments = (
                '{"conclusion":"被截断的结构化回答"'
                if round_number == 1 else "{}"
            )
            return ({
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": f"submit-{round_number}",
                    "type": "function",
                    "function": {"name": "submit_analysis", "arguments": arguments},
                }],
            }, {"total_tokens": 8}, f"response-{round_number}")

        async def progress(event: dict) -> None:
            events.append(event)

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
            api_timeout_seconds=5,
            model_max_retries=0,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent_runtime.service.get_settings", return_value=settings),
            patch("app.agent_runtime.service._stream_completion", new=fake_stream),
        ):
            result = asyncio.run(agent_module._run_agent_impl(
                "分析 CMP-03 最近7天 Cpk 不合格", [], "run-submit-retry-test", progress,
            ))

        self.assertEqual(len(requests), 2)
        self.assertEqual(
            [tool["function"]["name"] for tool in requests[1]["tools"]],
            ["submit_analysis"],
        )
        self.assertEqual(result["answer_synthesis"]["status"], "structured")
        self.assertEqual(
            result["answer_synthesis"]["repair_events"][0]["outcome"],
            "model_correction_accepted",
        )
        self.assertEqual(result["model_tool_selection_calls"], 0)
        validation_index = next(
            index for index, event in enumerate(events)
            if event.get("stage") == "validation"
        )
        first_answer_index = next(
            index for index, event in enumerate(events)
            if event.get("event") == "answer_delta"
        )
        self.assertLess(validation_index, first_answer_index)
        self.assertEqual(
            "".join(event.get("delta", "") for event in events if event.get("event") == "answer_delta"),
            result["answer"],
        )

    def test_legacy_repair_preserves_display_blocks_without_confirming_them(self):
        contract, sources = _supported_yield_contract()
        legacy = (
            "第一段保留引用 [来源 TOOL:get_fab_overview]。\n\n"
            "- 列表项一\n- 列表项二\n\n"
            "| 指标 | 值 |\n| --- | --- |\n| 良率 | 90% |"
        )

        repaired = synthesize_legacy_answer(legacy, contract, sources)

        self.assertEqual(repaired.report.status, "repaired")
        self.assertIn("第一段保留引用", repaired.answer)
        self.assertIn("第一段保留引用 [来源 TOOL:get_fab_overview]。\n\n- 列表项一\n- 列表项二", repaired.answer)
        self.assertIn("| 指标 | 值 |\n| --- | --- |\n| 良率 | 90% |", repaired.answer)
        self.assertNotIn("## 已确认事实", repaired.answer)
        self.assertEqual(repaired.report.repair_events[0]["outcome"], "preserved_as_unverified_blocks")

    def test_legacy_invalid_reference_remains_auditable(self):
        contract, sources = _supported_yield_contract()
        repaired = synthesize_legacy_answer("结论 [来源 NOT-A-SOURCE]", contract, sources)

        self.assertIn("NOT-A-SOURCE", repaired.report.invalid_source_refs)
        self.assertNotIn("NOT-A-SOURCE", repaired.report.source_refs)
        self.assertIn("[无效来源：NOT-A-SOURCE]", repaired.answer)
        self.assertIn("证据限制：以下原文", repaired.answer)

    def test_model_knowledge_legacy_preserves_layout_and_discloses_before_body(self):
        selection, plan = _context("查询 GaN 与 Si 器件工艺差异 SOP")
        contract = create_answer_contract(
            validate_evidence(plan, selection.selected_playbook, []),
            allow_model_knowledge_fallback=True,
        )
        legacy = "一般材料说明。\n\n- 宽禁带\n- 高击穿场强\n\n| 属性 | 说明 |\n| --- | --- |\n| GaN | 高频 |"
        repaired = synthesize_legacy_answer(legacy, contract)

        self.assertTrue(repaired.answer.startswith(MODEL_KNOWLEDGE_DISCLOSURE))
        self.assertIn("- 宽禁带\n- 高击穿场强", repaired.answer)
        self.assertIn("| 属性 | 说明 |\n| --- | --- |\n| GaN | 高频 |", repaired.answer)
        self.assertNotIn("## 已确认事实", repaired.answer)

    def test_model_repair_metadata_is_ignored_and_missing_fields_are_audited(self):
        contract, sources = _supported_yield_contract()
        result = synthesize_submission({
            "conclusion": "未验证结论", "facts": [], "inferences": [],
            "recommendations": [], "limitations": [],
            "_repair_events": None,
        }, contract, sources)
        self.assertNotIn("hidden reasoning", str(result.report.to_dict()))
        self.assertIn("missing_structured_field", {item["reason"] for item in result.report.repair_events})
        invalid = synthesize_submission({
            "facts": [{"statement": "声明", "evidence_refs": ["SECRET-REF"]}],
            "inferences": [], "hypotheses": [], "recommendations": [], "limitations": [],
            "_repair_events": "hidden reasoning secret",
        }, contract, sources)
        self.assertIn("SECRET-REF", invalid.report.invalid_source_refs)
        self.assertNotIn("hidden reasoning", str(invalid.report.to_dict()))


if __name__ == "__main__":
    unittest.main()
