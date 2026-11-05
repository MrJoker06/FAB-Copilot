"""Acceptance tests for the opt-in lithography Cpk Skill."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.bootstrap.litho_cpk_demo import run_litho_cpk_demo_sync


class LithoCpkSkillTests(unittest.TestCase):
    def test_ready_uses_existing_named_plan_and_all_native_fake_tools(self) -> None:
        result = run_litho_cpk_demo_sync("ready")
        plan = result["plan"]
        self.assertEqual(plan.playbook_id, "PB-CAPABILITY-001")
        self.assertEqual(plan.playbook_version, "2.0.0")
        self.assertEqual(
            [item["tool"] for item in result["trace"]],
            [
                "get_process_capability",
                "get_recent_excursions",
                "get_sensor_summary",
                "search_knowledge",
            ],
        )
        self.assertEqual(result["metadata"]["skill_id"], "litho-cpk-diagnostic")
        self.assertEqual(len(result["model_context"]), 1)
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["guard"].total_calls, 4)
        self.assertEqual(result["validation"].status, "validated")

    def test_loop_uses_the_same_guarded_plan(self) -> None:
        result = run_litho_cpk_demo_sync("loop")
        self.assertEqual(
            [item["tool"] for item in result["trace"]],
            [step.tool for step in result["plan"].steps],
        )
        self.assertEqual(result["validation"].plan_id, result["plan"].plan_id)
        self.assertEqual(result["model_calls"], 2)
        self.assertIn("lithography", result["model_context"][0].content.lower())
        request = result["model_requests"][1]
        self.assertEqual(
            [message.role for message in request.messages[-6:]],
            [
                "user",
                "assistant",
                "tool",
                "tool",
                "tool",
                "tool",
            ],
        )
        self.assertEqual(
            result["source_calls"],
            {
                "process_diagnostics": 2,
                "operational_reports": 1,
                "knowledge_search": 1,
            },
        )

    def test_explicit_resource_is_real_model_context_only(self) -> None:
        result = run_litho_cpk_demo_sync(
            "loop", resources=("references/cpk_context.md",)
        )
        self.assertEqual(len(result["model_context"]), 2)
        self.assertIn("references/cpk_context.md", result["model_context"][1].content)
        self.assertIn("references/cpk_context.md", result["metadata"]["loaded_paths"])
        self.assertIn("|", result["metadata"]["loaded_resources"])
        self.assertTrue(
            any(
                "references/cpk_context.md" in message.content
                for message in result["model_requests"][0].messages
            )
        )

    def test_viewer_is_denied_before_fake_sources_are_fetched(self) -> None:
        result = run_litho_cpk_demo_sync("ready", role="viewer")
        self.assertEqual(
            result["source_calls"],
            {
                "process_diagnostics": 0,
                "operational_reports": 0,
                "knowledge_search": 0,
            },
        )
        self.assertTrue(all(item["status"] == "blocked" for item in result["trace"]))
        self.assertEqual(result["guard"].total_calls, 0)

    def test_declared_acceptance_refs_match_the_controlled_binding(self) -> None:
        asset = (
            Path(__file__).parents[1]
            / "app"
            / "skills"
            / "lithography"
            / "cpk_diagnostic"
            / "scenarios"
            / "acceptance.json"
        )
        acceptance = json.loads(asset.read_text(encoding="utf-8"))
        result = run_litho_cpk_demo_sync("ready")
        self.assertEqual(
            acceptance["workflow"],
            {
                "component_id": result["metadata"]["workflow_id"],
                "version": result["metadata"]["workflow_version"],
            },
        )
        self.assertEqual(
            acceptance["evidence_policy"],
            {
                "component_id": result["metadata"]["evidence_policy_id"],
                "version": result["metadata"]["evidence_policy_version"],
            },
        )


if __name__ == "__main__":
    unittest.main()
