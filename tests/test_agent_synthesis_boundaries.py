from __future__ import annotations

import asyncio
import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime import service as agent
from app.evidence.answer_synthesizer import SUBMIT_ANALYSIS_TOOL
from app.manufacturing.playbooks import select_playbook
from app.intent_runtime.routing import route_question
from app.planning_runtime.service import create_execution_plan
from app.agent_runtime.synthesis.ready import ready_synthesis_max_tokens, synthesize_ready_assistant
from app.agent_runtime.synthesis.result import (
    build_ready_model_unavailable_result,
    build_result,
)


class AgentSynthesisBoundaryTests(unittest.TestCase):
    def test_ready_synthesis_token_budget_expands_only_for_deepseek_thinking(self):
        self.assertEqual(ready_synthesis_max_tokens("deepseek", True), 32768)
        self.assertEqual(ready_synthesis_max_tokens("deepseek", False), 8192)
        self.assertEqual(ready_synthesis_max_tokens("openai-compatible", True), 8192)

    def test_ready_request_payload_uses_thinking_budget_only_for_deepseek(self):
        captured = []
        async def completion(_client, _endpoint, _headers, payload, _progress, state):
            captured.append(payload); state["finish_reason"] = "tool_calls"; return {"tool_calls": []}, {}, "r"
        class Settings: model_retry_base_seconds = 0
        for provider, thinking in (("deepseek", True), ("deepseek", False), ("openai-compatible", True)):
            connection = SimpleNamespace(model="m", provider=provider)
            with patch("app.agent_runtime.service._stream_completion", completion), patch("app.agent_runtime.service.emit"):
                asyncio.run(agent._request_ready_synthesis(None, "e", {}, connection, Settings(), [], "run", thinking, 0))
        self.assertEqual([payload["max_tokens"] for payload in captured], [32768, 8192, 8192])

    def test_ready_messages_facade_uses_live_synthesizer_patch(self):
        route = route_question("分析 CMP-03 最近7天 Cpk 不合格", current_date=date(2026, 8, 23))
        plan = create_execution_plan("分析 CMP-03 最近7天 Cpk 不合格", route, select_playbook(route))
        validation = agent.validate_evidence(plan, select_playbook(route).selected_playbook, [])
        contract = agent.create_answer_contract(validation)
        with patch("app.agent_runtime.service.synthesizer_system_message", return_value="live-contract"):
            messages = agent._ready_synthesis_messages("问题", plan, validation, contract, [])
        self.assertEqual(messages[1]["content"], "live-contract")

    def test_ready_messages_remain_three_and_preserve_evidence_json(self):
        route = route_question("分析 CMP-03 最近7天 Cpk 不合格", current_date=date(2026, 8, 23))
        plan = create_execution_plan("分析 CMP-03 最近7天 Cpk 不合格", route, select_playbook(route))
        validation = agent.validate_evidence(plan, select_playbook(route).selected_playbook, [])
        contract = agent.create_answer_contract(validation)
        messages = agent._ready_synthesis_messages("问题", plan, validation, contract, [])
        self.assertEqual(len(messages), 3)
        payload = json.loads(messages[2]["content"])
        self.assertEqual(payload["question"], "问题")
        self.assertEqual(payload["evidence"], [])

    def test_ready_contract_uses_current_format_before_resolved_format(self):
        route = route_question("分析 CMP-03 最近7天 Cpk 不合格", current_date=date(2026, 8, 23))
        plan = create_execution_plan("分析 CMP-03 最近7天 Cpk 不合格", route, select_playbook(route))
        validation = agent.validate_evidence(plan, select_playbook(route).selected_playbook, [])
        current = agent.create_answer_contract(
            validation, question="一句话总结", resolved_question="请用表格比较",
        )
        restored = agent.create_answer_contract(
            validation, question="继续分析", resolved_question="请用表格比较",
        )
        self.assertIn('"presentation":"brief"', agent._ready_synthesis_messages("问题", plan, validation, current, [])[1]["content"])
        self.assertIn('"presentation":"table"', agent._ready_synthesis_messages("问题", plan, validation, restored, [])[1]["content"])

    def test_ready_messages_preserve_compact_ordered_evidence_json(self):
        route = route_question("分析 CMP-03 最近7天 Cpk 不合格", current_date=date(2026, 8, 23))
        plan = create_execution_plan("分析 CMP-03 最近7天 Cpk 不合格", route, select_playbook(route))
        validation = agent.validate_evidence(plan, select_playbook(route).selected_playbook, [])
        contract = agent.create_answer_contract(validation)
        observations = [
            SimpleNamespace(source_ref="OK-1", tool="tool_one", status="success", result={"value": "成功"}, error=None),
            SimpleNamespace(source_ref="FAIL-2", tool="tool_two", status="failed", result={"ignored": True}, error="错误"),
        ]
        messages = agent._ready_synthesis_messages("问题", plan, validation, contract, observations)
        expected_evidence = [
            {"source_ref": "OK-1", "tool": "tool_one", "status": "success", "result": {"value": "成功"}, "error": None},
            {"source_ref": "FAIL-2", "tool": "tool_two", "status": "failed", "result": None, "error": "错误"},
        ]
        expected_suffix = '"evidence":' + json.dumps(
            expected_evidence, ensure_ascii=False, separators=(",", ":"), default=str,
        ) + "}"
        self.assertTrue(messages[2]["content"].endswith(expected_suffix))

    def test_ready_request_exposes_only_submit_tool(self):
        events = []
        async def completion(_client, _endpoint, _headers, payload, _progress, state):
            self.assertEqual(payload["tools"], [SUBMIT_ANALYSIS_TOOL])
            self.assertNotIn("get_fab_overview", str(payload))
            state["finish_reason"] = "tool_calls"
            return {"tool_calls": []}, {}, "r"
        class Connection: model = "m"; provider = "other"
        class Settings: model_retry_base_seconds = 0
        with patch("app.agent_runtime.service._stream_completion", completion), patch("app.agent_runtime.service.emit", side_effect=lambda *args, **kwargs: events.append(args[0])):
            asyncio.run(agent._request_ready_synthesis(None, "e", {}, Connection(), Settings(), [], "run", False, 0))
        self.assertEqual(events, ["model_call_started", "model_call_finished"])

    def test_offline_fallback_uses_live_local_handlers(self):
        route = route_question("分析最近良率", current_date=date(2026, 8, 23))
        plan = create_execution_plan("分析最近良率", route, select_playbook(route))
        with patch("app.agent_runtime.service.fab_overview", return_value={"lots": 1, "yield_pct": 99, "avg_cycle_hours": 2}), patch("app.agent_runtime.service.equipment_health", return_value=[]):
            result = agent._offline_answer("分析最近良率", route, select_playbook(route), plan, agent.ToolLoopGuard(plan))
        self.assertEqual(result["tool_trace"][0], {"tool": "get_fab_overview", "status": "local"})
        self.assertEqual(result["tool_trace"][1]["tool"], "get_equipment_health")

    def test_invalid_submit_analysis_emits_rejection_then_fallback(self):
        events = []
        fallback = SimpleNamespace(answer="fallback", report=SimpleNamespace(status="fallback"))
        deps = agent._ready_synthesis_dependencies()
        deps.emit = lambda *args, **kwargs: events.append((args, kwargs))
        deps.synthesize_legacy_answer = lambda *_args, **_kwargs: fallback
        deps.ready_synthesis_fallback = lambda *_args, **_kwargs: fallback
        result = synthesize_ready_assistant(
            {"tool_calls": [{"function": {"name": "submit_analysis", "arguments": "{"}}]},
            object(), [], SimpleNamespace(coverage={"required_covered": 0, "required_total": 0}, allowed_conclusion_strength="none"), [], "run", deps=deps,
        )
        self.assertIs(result, fallback)
        self.assertEqual(events[0][0][0], "answer_submission_rejected")

    def test_missing_submit_analysis_uses_fallback(self):
        fallback = SimpleNamespace(answer="fallback", report=SimpleNamespace(status="fallback"))
        deps = agent._ready_synthesis_dependencies()
        deps.synthesize_legacy_answer = lambda *_args, **_kwargs: fallback
        deps.ready_synthesis_fallback = lambda *_args, **_kwargs: fallback
        result = synthesize_ready_assistant(
            {"tool_calls": [], "content": ""}, object(), [],
            SimpleNamespace(coverage={"required_covered": 0, "required_total": 0}, allowed_conclusion_strength="none"), [], "run", deps=deps,
        )
        self.assertIs(result, fallback)

    def test_ready_assistant_preserves_nonempty_content_whitespace(self):
        report = SimpleNamespace(answer="answer", report=SimpleNamespace(status="legacy"))
        raw_content = "  保留前后空白\n"
        with patch("app.agent_runtime.service.synthesize_legacy_answer", return_value=report) as synthesize:
            result = agent._synthesize_ready_assistant(
                {"tool_calls": [], "content": raw_content},
                object(),
                [],
                SimpleNamespace(),
                [],
                "run",
            )
        self.assertIs(result, report)
        self.assertEqual(synthesize.call_args.args[0], raw_content)

    def test_ready_assistant_uses_live_fallback_facade_patch(self):
        fallback = SimpleNamespace(answer="fallback", report=SimpleNamespace(status="fallback"))
        contract = object()
        validation = SimpleNamespace()
        observations = []
        with patch("app.agent_runtime.service._ready_synthesis_fallback", return_value=fallback) as facade:
            result = agent._synthesize_ready_assistant(
                {"tool_calls": [], "content": ""},
                contract,
                [],
                validation,
                observations,
                "run",
            )
        self.assertIs(result, fallback)
        facade.assert_called_once_with(
            validation,
            contract,
            observations,
            "模型没有提交允许的 submit_analysis 结果",
        )

    def test_offline_clarification_does_not_call_local_tools(self):
        route = route_question("你好", current_date=date(2026, 8, 23))
        plan = create_execution_plan("你好", route, select_playbook(route))
        clarification = SimpleNamespace(strategy="context_clarification", candidate_messages=[], recalled_messages=[])
        with patch("app.agent_runtime.service.fab_overview", side_effect=AssertionError), patch("app.agent_runtime.service.equipment_health", side_effect=AssertionError):
            result = agent._offline_answer("你好", route, select_playbook(route), plan, agent.ToolLoopGuard(plan), clarification)
        self.assertEqual(result["tool_trace"], [])

    def test_result_filters_sources_and_preserves_key_fields(self):
        report = SimpleNamespace(source_refs=("KB-1", "TOOL:x"), to_dict=lambda: {"status": "structured"})
        value = build_result(
            "answer", report, trace=[], sources={"KB-1": {"reference_id": "KB-1"}, "KB-2": {"reference_id": "KB-2"}},
            intent_route=SimpleNamespace(intent="fab_diagnostic"), connection=SimpleNamespace(model="m"), total_usage={}, route_payload={}, playbook_payload={}, plan_payload={},
            loop_guard=SimpleNamespace(summary=lambda: {}), evidence_validation=SimpleNamespace(to_dict=lambda: {}), answer_contract=SimpleNamespace(to_dict=lambda: {}), context_resolution=SimpleNamespace(to_dict=lambda: {}), knowledge_fallback={}, retrieval_decision_payload={"selected_reference_ids": []}, thinking=False, thinking_answer_effective=False, turn_decision=SimpleNamespace(to_dict=lambda: {}),
        )
        self.assertEqual(value["sources"], [{"reference_id": "KB-1"}])
        self.assertIn("thinking_policy", value)

    def test_early_ready_no_model_result_has_contract_fields(self):
        report = SimpleNamespace(to_dict=lambda: {"status": "fallback"})
        result = build_ready_model_unavailable_result(
            "answer", report, trace=[], route_payload={}, playbook_payload={}, plan_payload={}, loop_guard=SimpleNamespace(summary=lambda: {}),
            evidence_validation=SimpleNamespace(to_dict=lambda: {}), answer_contract=SimpleNamespace(to_dict=lambda: {}), context_resolution=SimpleNamespace(to_dict=lambda: {}), thinking=True, turn_decision=SimpleNamespace(to_dict=lambda: {}), selected_model_id="id", fallback_reason="circuit_open", model_health={"status": "open"}, usage={},
        )
        self.assertEqual(result["retrieval_decision"]["state"], "NOT_APPLICABLE")
        self.assertEqual(result["model_tool_selection_calls"], 0)


if __name__ == "__main__":
    unittest.main()
