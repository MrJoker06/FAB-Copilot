from __future__ import annotations

import copy
import unittest

from scripts import evaluate_playbooks


class PlaybookEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = evaluate_playbooks.load_dataset()

    def test_current_golden_dataset_passes(self):
        report = evaluate_playbooks.evaluate_dataset(self.dataset)
        self.assertTrue(report["passed"])
        self.assertEqual(report["cases"], 12)
        self.assertEqual(report["failed_cases"], [])

    def test_dataset_validation_rejects_missing_intent_and_duplicate_id(self):
        dataset = copy.deepcopy(self.dataset)
        dataset["cases"] = dataset["cases"][:-2]
        dataset["cases"][1]["id"] = dataset["cases"][0]["id"]
        errors = evaluate_playbooks.validate_dataset(dataset)
        self.assertIn("duplicate case id: capability-cmp-relative", errors)
        self.assertIn("missing required intents: fab_diagnostic", errors)

    def test_dataset_validation_requires_two_cases_per_intent(self):
        dataset = copy.deepcopy(self.dataset)
        dataset["cases"] = [case for case in dataset["cases"] if case["id"] != "capability-cmp-explicit"]
        errors = evaluate_playbooks.validate_dataset(dataset)
        self.assertIn("intent capability_excursion requires at least 2 cases, got 1", errors)

    def test_dataset_validation_rejects_invalid_case_schema(self):
        dataset = copy.deepcopy(self.dataset)
        dataset["current_date"] = "not-a-date"
        dataset["cases"][0].pop("tool_path")
        errors = evaluate_playbooks.validate_dataset(dataset)
        self.assertIn("current_date must be an ISO date", errors)
        self.assertIn("cases[0].tool_path must be a non-empty list", errors)

    def test_path_mismatch_is_reported_for_the_specific_case(self):
        dataset = copy.deepcopy(self.dataset)
        dataset["cases"][0]["tool_path"] = ["search_knowledge"]
        report = evaluate_playbooks.evaluate_dataset(dataset)
        failure = next(item for item in report["failed_cases"] if item["id"] == "capability-cmp-relative")
        self.assertFalse(failure["passed"])
        self.assertTrue(any(reason.startswith("tool_path expected") for reason in failure["reasons"]))


if __name__ == "__main__":
    unittest.main()
