from __future__ import annotations

import unittest

from scripts.evaluate_ready_execution import evaluate, load_dataset


class ReadyExecutionBenchmarkTests(unittest.TestCase):
    def test_dataset_records_fixed_offline_baseline_and_thresholds(self):
        dataset = load_dataset()

        self.assertEqual(dataset["baseline_mode"], "legacy_model_selects_each_dependency_ready_batch_then_synthesizes")
        self.assertEqual(dataset["candidate_mode"], "server_executes_ready_plan_then_model_synthesizes_once")
        self.assertGreaterEqual(len(dataset["cases"]), 3)
        self.assertEqual(dataset["thresholds"]["total_token_reduction_pct_min"], 20)
        self.assertEqual(dataset["thresholds"]["first_final_answer_reduction_pct_min"], 20)

    def test_candidate_has_no_model_tool_selection_and_meets_reduction_gate(self):
        report = evaluate()

        self.assertTrue(report["passed"], report)
        for detail in report["details"]:
            with self.subTest(case=detail["id"]):
                self.assertEqual(detail["candidate"]["model_tool_selection_calls"], 0)
                self.assertEqual(detail["candidate"]["model_calls"], 1)
                self.assertGreaterEqual(detail["improvement"]["total_token_reduction_pct"], 20)
                self.assertGreaterEqual(detail["improvement"]["first_final_answer_reduction_pct"], 20)


if __name__ == "__main__":
    unittest.main()
