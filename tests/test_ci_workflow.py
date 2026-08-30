from __future__ import annotations

import unittest
from pathlib import Path

import yaml


WORKFLOW_DIR = Path(__file__).parents[1] / ".github" / "workflows"
WORKFLOW_PATH = WORKFLOW_DIR / "quality.yml"
LIVE_WORKFLOW_PATH = WORKFLOW_DIR / "live-quality.yml"


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
        self.assertEqual(self.workflow["jobs"]["quality"]["runs-on"], "ubuntu-24.04")

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
        font_step = next(step for step in steps if step.get("name") == "Install deterministic visual fonts")
        self.assertIn("fonts-noto-core fonts-noto-cjk", font_step["run"])
        self.assertIn("fc-cache -f", font_step["run"])
        self.assertIn("python scripts/prepare_ci_data.py", rendered)
        self.assertIn("python scripts/run_quality_gate.py full", rendered)

    def test_failure_diagnostics_have_retention_and_exclude_databases_logs_and_secrets(self):
        artifact = next(step for step in self.workflow["jobs"]["quality"]["steps"] if step.get("uses") == "actions/upload-artifact@v7")
        self.assertEqual(artifact["if"], "${{ failure() && !cancelled() }}")
        self.assertEqual(artifact["with"]["retention-days"], "14")
        self.assertIn("actions/upload-artifact@v7", self.text)
        self.assertEqual(artifact["with"]["path"], "playwright-report/\ntest-results/\nruntime/quality/\n")
        self.assertNotIn("secrets.", self.text.lower())
        self.assertNotIn("oracle", self.text.lower())
        self.assertNotIn("deepseek", self.text.lower())
        self.assertNotIn("*.db", self.text)

    def test_live_workflow_is_manual_protected_and_uses_only_server_secret(self):
        workflow = yaml.load(LIVE_WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        rendered = LIVE_WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertEqual(workflow["on"], {"workflow_dispatch": {"inputs": {"model_id": {"description": "Published, compatibility-verified model catalog ID", "required": "true", "type": "string"}}}})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["live-e2e"]
        self.assertEqual(job["name"], "Live E2E quality gate")
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        self.assertEqual(job["timeout-minutes"], "20")
        self.assertEqual(job["environment"], "live-e2e")
        self.assertEqual(job["env"], {"CI": "true"})
        self.assertFalse(set(job["env"]) & {"FAB_LIVE_E2E_TARGET", "FAB_LIVE_E2E_AUTHORIZED", "FAB_LIVE_MODEL_ID", "FAB_MODEL_API_KEY"})
        run = next(step for step in job["steps"] if step.get("name") == "Run full authorized Live E2E gate")
        self.assertEqual(run["env"], {"FAB_LIVE_E2E_TARGET": "full", "FAB_LIVE_E2E_AUTHORIZED": "true", "FAB_LIVE_MODEL_ID": "${{ inputs.model_id }}", "FAB_MODEL_API_KEY": "${{ secrets.FAB_MODEL_API_KEY }}"})
        self.assertEqual(rendered.count("secrets."), 1)
        self.assertNotIn("DEEPSEEK_API_KEY", rendered)
        self.assertIn("python scripts/run_quality_gate.py live", rendered)

    def test_live_workflow_uses_fixed_runtimes_and_only_safe_metadata_artifact(self):
        workflow = yaml.load(LIVE_WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        job = workflow["jobs"]["live-e2e"]
        steps = job["steps"]
        python_setup = next(step for step in steps if step.get("uses") == "actions/setup-python@v6")
        node_setup = next(step for step in steps if step.get("uses") == "actions/setup-node@v6")
        self.assertEqual(python_setup["with"]["python-version"], "3.11")
        self.assertEqual(node_setup["with"]["node-version"], "22")
        self.assertIn("npx playwright install --with-deps chromium", "\n".join(str(step) for step in steps))
        artifact = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v7")
        self.assertEqual(artifact["if"], "${{ always() && !cancelled() }}")
        self.assertEqual(artifact["with"]["path"], "runtime/quality/live_e2e_report.json")
        self.assertNotIn("playwright-report", str(artifact))
        self.assertNotIn("test-results", str(artifact))
