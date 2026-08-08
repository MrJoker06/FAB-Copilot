from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import agent as agent_module
from app.domain_playbooks import DOMAIN_PLAYBOOKS, playbook_system_message, select_playbook
from app.intent_router import route_question


class DomainPlaybookTests(unittest.TestCase):
    def test_registry_contains_six_versioned_playbooks(self):
        self.assertEqual(
            set(DOMAIN_PLAYBOOKS),
            {"capability_excursion", "yield_decline", "equipment_fault", "lot_trace", "sop_lookup", "fab_diagnostic"},
        )
        playbook_ids: set[str] = set()
        for intent, playbook in DOMAIN_PLAYBOOKS.items():
            with self.subTest(intent=intent):
                self.assertEqual(playbook.intent, intent)
                self.assertRegex(playbook.playbook_id, r"^PB-[A-Z]+-[0-9]{3}$")
                self.assertRegex(playbook.schema_version, r"^[0-9]+\.[0-9]+$")
                self.assertRegex(playbook.playbook_version, r"^[0-9]+\.[0-9]+\.[0-9]+$")
                self.assertRegex(playbook.released_at, r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
                self.assertNotIn(playbook.playbook_id, playbook_ids)
                playbook_ids.add(playbook.playbook_id)
                self.assertTrue(playbook.required_inputs)
                self.assertTrue(playbook.analysis_questions)
                self.assertTrue(playbook.answer_sections)
                self.assertTrue(playbook.safety_constraints)

    def test_evidence_templates_are_complete_and_only_reference_available_tools(self):
        available_tools = set(agent_module.TOOL_HANDLERS)
        evidence_ids: set[str] = set()

        for playbook in DOMAIN_PLAYBOOKS.values():
            required_count = 0
            for evidence in playbook.evidence_requirements:
                with self.subTest(playbook=playbook.playbook_id, evidence=evidence.evidence_id):
                    self.assertNotIn(evidence.evidence_id, evidence_ids)
                    evidence_ids.add(evidence.evidence_id)
                    self.assertTrue(evidence.name)
                    self.assertTrue(evidence.purpose)
                    self.assertTrue(evidence.source_tools)
                    self.assertTrue(set(evidence.source_tools).issubset(available_tools))
                    self.assertTrue(evidence.required_fields)
                    self.assertTrue(evidence.acceptance_criteria)
                    required_count += int(evidence.required)
            self.assertGreater(required_count, 0, playbook.playbook_id)

    def test_domain_specific_evidence_contracts_are_present(self):
        expected_required = {
            "capability_excursion": {"CAP-01", "CAP-02", "CAP-04"},
            "yield_decline": {"YLD-01", "YLD-02", "YLD-03"},
            "equipment_fault": {"EQP-01", "EQP-02", "EQP-03", "EQP-04", "EQP-05"},
            "lot_trace": {"LOT-01", "LOT-02", "LOT-03", "LOT-04"},
            "sop_lookup": {"SOP-01", "SOP-02"},
            "fab_diagnostic": {"FAB-01", "FAB-02", "FAB-03", "FAB-04"},
        }
        for intent, required_ids in expected_required.items():
            actual = {
                item.evidence_id
                for item in DOMAIN_PLAYBOOKS[intent].evidence_requirements
                if item.required
            }
            self.assertEqual(actual, required_ids)

    def test_selects_exact_playbook_for_each_supported_route(self):
        cases = (
            ("分析 CMP Cpk 不合格", "PB-CAPABILITY-001"),
            ("最近四周良率下降", "PB-YIELD-001"),
            ("检查 ETCH-04 故障报警", "PB-EQUIPMENT-001"),
            ("追踪批次 L260708-02460", "PB-LOT-001"),
            ("查询 CMP 恢复量产 SOP", "PB-SOP-001"),
            ("关于目前的制造数据你有什么改进建议", "PB-FAB-001"),
        )
        for question, expected_id in cases:
            with self.subTest(question=question):
                selection = select_playbook(route_question(question))
                self.assertEqual(selection.status, "selected")
                self.assertIsNotNone(selection.selected_playbook)
                self.assertEqual(selection.selected_playbook.playbook_id, expected_id)
                self.assertEqual(len(selection.candidate_playbooks), 1)

    def test_ambiguous_route_requires_clarification_without_selecting_template(self):
        selection = select_playbook(route_question("设备健康和良率趋势"))

        self.assertEqual(selection.status, "clarification_required")
        self.assertIsNone(selection.selected_playbook)
        self.assertEqual(
            {item.playbook_id for item in selection.candidate_playbooks},
            {"PB-EQUIPMENT-001", "PB-YIELD-001"},
        )
        self.assertIn("不得混合执行候选模板", playbook_system_message(selection))

    def test_unsupported_route_keeps_generic_agent_path(self):
        selection = select_playbook(route_question("分析 CMP 划伤缺陷 Pareto"))

        self.assertEqual(selection.status, "unsupported")
        self.assertIsNone(selection.selected_playbook)
        self.assertEqual(selection.candidate_playbooks, ())

    def test_agent_loop_injects_selected_playbook_and_returns_version(self):
        captured: dict = {}
        progress_events: list[dict] = []

        async def fake_stream(client, endpoint, headers, request_payload, progress, stream_state):
            captured.update(request_payload)
            return ({"role": "assistant", "content": "Playbook 测试完成"}, {"total_tokens": 4}, "playbook-response")

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
                    "run-domain-playbook-test",
                    progress,
                )
            )

        selected = result["domain_playbook"]["selected_playbook"]
        self.assertEqual(selected["playbook_id"], "PB-CAPABILITY-001")
        self.assertEqual(selected["playbook_version"], "1.0.0")
        self.assertTrue(any(item.get("stage") == "playbook" for item in progress_events))

        playbook_message = captured["messages"][2]
        self.assertEqual(playbook_message["role"], "system")
        payload = json.loads(playbook_message["content"].split("domain_playbook=", 1)[1])
        self.assertEqual(payload["status"], "selected")
        self.assertEqual(payload["selected_playbook"]["playbook_id"], "PB-CAPABILITY-001")
        required_evidence = {
            item["evidence_id"]
            for item in payload["selected_playbook"]["evidence_requirements"]
            if item["required"]
        }
        self.assertEqual(required_evidence, {"CAP-01", "CAP-02", "CAP-04"})


if __name__ == "__main__":
    unittest.main()
