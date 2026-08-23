from __future__ import annotations

import copy
import json
import socket
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.evaluate_trace_replay import evaluate, evaluate_dataset, load_dataset, replay_case


class TraceReplayTests(unittest.TestCase):
    def test_dataset_has_three_real_chains_router_replays_and_counterexample(self):
        dataset = load_dataset()
        groups = [case["group"] for case in dataset["cases"]]

        self.assertEqual(groups.count("real_chain"), 3)
        self.assertGreaterEqual(groups.count("router_failure_replay"), 3)
        self.assertGreaterEqual(groups.count("counterexample"), 1)
        self.assertEqual(
            {case["id"] for case in dataset["cases"] if case.get("system_replay")},
            {"chain-general-knowledge", "chain-cmp-capability", "chain-fab-diagnostic"},
        )
        self.assertEqual(dataset["execution_policy"]["network_calls"], 0)
        self.assertEqual(dataset["execution_policy"]["real_model_calls"], 0)

    def test_all_cross_layer_gold_expectations_pass_offline(self):
        report = evaluate()

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["passed_cases"], report["cases"])
        self.assertEqual(report["external_calls"], {"network": 0, "real_model": 0})
        self.assertEqual(report["groups"]["real_chain"], 3)
        for detail in report["details"]:
            with self.subTest(case=detail["id"]):
                self.assertFalse(detail["errors"])
                self.assertLessEqual(detail["model_calls"], 1)
                self.assertEqual(detail["business_tool_calls"], len(detail["tool_path"]))

    def test_replay_does_not_require_socket_access(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            report = evaluate()
        self.assertTrue(report["passed"], report)

    def test_gold_mismatch_fails_closed(self):
        dataset = copy.deepcopy(load_dataset())
        dataset["cases"][0]["expected"]["route"] = "fab_diagnostic"

        report = evaluate_dataset(dataset)

        self.assertFalse(report["passed"])
        self.assertEqual(report["failed_cases"], ["chain-general-knowledge"])
        self.assertIn("route:", report["details"][0]["errors"][0])

    def test_ready_replays_preserve_plan_scope_submission_and_stream(self):
        dataset = load_dataset()
        current_date = date.fromisoformat(dataset["current_date"])
        ready_cases = [
            case for case in dataset["cases"]
            if case["expected"]["plan_status"] == "ready"
        ]

        for case in ready_cases:
            with self.subTest(case=case["id"]):
                result = replay_case(case, current_date=current_date)
                plan = result["execution_plan"]
                expected = case["expected"]
                streamed = "".join(
                    event.get("delta", "")
                    for event in result["replay"]["progress_events"]
                    if event.get("event") == "answer_delta"
                )
                self.assertEqual(plan["scope_contract"]["primary_scope_type"], expected["primary_scope_type"])
                self.assertEqual(plan["scope_contract"]["primary_scope_ids"], expected["primary_scope_ids"])
                self.assertEqual(result["answer_synthesis"]["status"], "structured")
                self.assertEqual(result["answer_synthesis"]["invalid_source_refs"], [])
                self.assertEqual(streamed, result["answer"])
                self.assertEqual(len(result["tool_trace"]), plan["budget"]["planned_tool_calls"])
                self.assertEqual(result["trace_semantics"]["model_business_tool_selection_calls"], 0)

    def test_dataset_rejects_sensitive_or_hidden_reasoning_fields(self):
        dataset = copy.deepcopy(load_dataset())
        dataset["cases"][0]["api_key"] = "placeholder"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json"
            path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "forbidden fields"):
                load_dataset(path)


if __name__ == "__main__":
    unittest.main()
