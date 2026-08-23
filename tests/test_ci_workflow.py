from __future__ import annotations

import unittest
from pathlib import Path

import yaml


WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml"


class CiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.text = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_workflow_is_safe_yaml_with_exact_events_and_permissions(self):
        self.assertEqual(self.workflow["on"]["push"]["branches"], ["experiment/parallel-platform"])
        self.assertEqual(self.workflow["on"]["pull_request"]["branches"], ["experiment/parallel-platform"])
        self.assertEqual(self.workflow["on"]["workflow_dispatch"], "")
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(self.workflow["concurrency"]["cancel-in-progress"], "true")
        self.assertEqual(self.workflow["jobs"]["quality"]["name"], "Full quality gate")

    def test_workflow_has_fixed_runtimes_and_full_offline_quality_path(self):
        steps = self.workflow["jobs"]["quality"]["steps"]
        rendered = "\n".join(str(step) for step in steps)
        python_setup = next(step for step in steps if step.get("uses") == "actions/setup-python@v6")
        node_setup = next(step for step in steps if step.get("uses") == "actions/setup-node@v6")
        self.assertIn("actions/checkout@v6", rendered)
        self.assertIn("actions/setup-python@v6", rendered)
        self.assertEqual(python_setup["with"]["python-version"], "3.11")
        self.assertEqual(python_setup["with"]["cache-dependency-path"], "requirements.txt\nrequirements-test.txt\n")
        self.assertIn("actions/setup-node@v6", rendered)
        self.assertEqual(node_setup["with"]["node-version"], "22")
        self.assertIn("python -m pip install -r requirements-test.txt", rendered)
        self.assertIn("npm ci", rendered)
        self.assertIn("npx playwright install --with-deps chromium", rendered)
        self.assertIn("python scripts/prepare_ci_data.py", rendered)
        self.assertIn("python scripts/run_quality_gate.py full", rendered)

    def test_failure_diagnostics_have_retention_and_exclude_databases_logs_and_secrets(self):
        artifact = next(step for step in self.workflow["jobs"]["quality"]["steps"] if step.get("uses") == "actions/upload-artifact@v5")
        self.assertEqual(artifact["if"], "${{ failure() && !cancelled() }}")
        self.assertEqual(artifact["with"]["retention-days"], "14")
        self.assertIn("actions/upload-artifact@v5", self.text)
        self.assertEqual(artifact["with"]["path"], "playwright-report/\ntest-results/\nruntime/quality/\n")
        self.assertNotIn("secrets.", self.text.lower())
        self.assertNotIn("oracle", self.text.lower())
        self.assertNotIn("deepseek", self.text.lower())
        self.assertNotIn("*.db", self.text)
