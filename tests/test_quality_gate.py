from __future__ import annotations

import sys
import tempfile
import unittest
import json
import subprocess
from unittest.mock import patch
from pathlib import Path

from scripts import run_quality_gate


class QualityGateTests(unittest.TestCase):
    def test_command_sets_keep_full_suite_and_quick_excludes_system(self):
        quick = run_quality_gate.quality_commands("quick")
        full = run_quality_gate.quality_commands("full")
        self.assertIn("tests.test_quality_gate", quick[0])
        self.assertFalse(any(module.startswith("tests.system.") for module in quick[0]))
        self.assertIn([sys.executable, "-m", "coverage", "run", "--branch", "--source=app", "-m", "unittest", *run_quality_gate.python_test_modules(False)], full)
        self.assertEqual(full[-1], [sys.executable, "-m", "coverage", "report", "--include", "app/*", "--fail-under=80"])
        self.assertEqual(full.count(["npm", "run", "test:e2e"]), 1)
        self.assertEqual(quick.count(["npm", "run", "test:e2e"]), 0)
        self.assertEqual(quick[-4:], [
            [sys.executable, "scripts/evaluate_rag.py"],
            [sys.executable, "scripts/evaluate_ocr.py"],
            [sys.executable, "scripts/evaluate_playbooks.py"],
            [sys.executable, "scripts/evaluate_ready_execution.py"],
        ])
        self.assertIn([sys.executable, "scripts/check_repository.py"], quick)
        self.assertIn([sys.executable, "scripts/check_repository.py"], full)

    def test_full_gate_runs_coverage_before_all_remaining_checks(self):
        commands = run_quality_gate.quality_commands("full")
        coverage_report = commands.pop(-1)
        calls = []
        with (
            patch.object(run_quality_gate, "count_python_tests", return_value=run_quality_gate.MIN_PYTHON_TESTS),
            patch.object(run_quality_gate, "run_commands", side_effect=lambda commands, *args: calls.append(list(commands))),
            patch.object(run_quality_gate, "run_system_tests", side_effect=lambda *args: calls.append(["system"])),
        ):
            self.assertEqual(run_quality_gate.main(["full"]), 0)
        self.assertEqual(calls[0], commands[:2])
        self.assertEqual(calls[1], ["system"])
        self.assertEqual(calls[2][0], coverage_report)
        self.assertIn([sys.executable, "scripts/check_repository.py"], calls[2])

    def test_commands_cover_node_tests_and_every_static_script(self):
        commands = run_quality_gate.quality_commands("quick")
        node_command = next(command for command in commands if command[:2] == ["node", "--test"])
        self.assertTrue(node_command[2:])
        self.assertTrue(all(Path(path).is_file() for path in node_command[2:]))
        checks = [command[2] for command in commands if command[:2] == ["node", "--check"]]
        self.assertTrue(checks)
        self.assertTrue(all(Path(path).is_file() for path in checks))

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            run_quality_gate.quality_commands("nightly")

    def test_ast_count_avoids_importing_test_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "test_sample.py").write_text(
                "raise RuntimeError('must not import')\n"
                "class Sample:\n"
                "    def test_one(self): pass\n"
                "    async def test_two(self): pass\n"
                "    def helper(self): pass\n",
                encoding="utf-8",
            )
            self.assertEqual(run_quality_gate.count_python_tests(directory), 2)
        self.assertGreaterEqual(run_quality_gate.MIN_PYTHON_TESTS, 175)

    def test_recursive_modules_and_count_use_package_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "tests"
            nested = directory / "system"
            nested.mkdir(parents=True)
            (directory / "test_root.py").write_text("class Root:\n    def test_one(self): pass\n", encoding="utf-8")
            path = nested / "test_domain.py"
            path.write_text("class Domain:\n    def test_two(self): pass\n", encoding="utf-8")
            self.assertEqual(run_quality_gate.count_python_tests(directory), 2)
            self.assertEqual(run_quality_gate.module_name_for_path(path, directory), "tests.system.test_domain")

    def test_system_runner_appends_each_module_once_and_records_warning(self):
        budgets = {
            "schema_version": 1,
            "modules": {"tests.system.test_a": {"warning_seconds": 2, "fail_seconds": 4}},
            "total": {"warning_seconds": 2, "fail_seconds": 4},
        }
        calls = []
        ticks = iter((0, 0, 3, 3.5))
        report_path = Path(tempfile.gettempdir()) / "system-timings-test.json"
        def runner(command, **kwargs):
            calls.append(command)
        with (
            patch.object(run_quality_gate, "load_system_test_budgets", return_value=budgets),
            patch.object(run_quality_gate, "system_test_modules", return_value=["tests.system.test_a"]),
            patch.object(run_quality_gate, "SYSTEM_TIMINGS_PATH", report_path),
        ):
            run_quality_gate.run_system_tests({}, runner=runner, clock=lambda: next(ticks))
        self.assertEqual(len(calls), 1)
        self.assertIn("--append", calls[0])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["modules"][0]["test_status"], "passed")
        self.assertEqual(report["modules"][0]["budget_status"], "warning")
        self.assertEqual(report["modules"][0]["status"], "warning")
        self.assertEqual(report["total"]["status"], "warning")

    def test_budget_boundaries(self):
        budget = {"warning_seconds": 2, "fail_seconds": 3}
        self.assertEqual(run_quality_gate._budget_status(1.9, budget), "passed")
        self.assertEqual(run_quality_gate._budget_status(2, budget), "warning")
        self.assertEqual(run_quality_gate._budget_status(3, budget), "warning")
        self.assertEqual(run_quality_gate._budget_status(3.01, budget), "failed")

    def test_system_runner_rejects_fail_budget(self):
        budgets = {
            "schema_version": 1,
            "modules": {"tests.system.test_a": {"warning_seconds": 1, "fail_seconds": 2}},
            "total": {"warning_seconds": 4, "fail_seconds": 5},
        }
        ticks = iter((0, 0, 2.1, 2.2))
        with (
            patch.object(run_quality_gate, "load_system_test_budgets", return_value=budgets),
            patch.object(run_quality_gate, "system_test_modules", return_value=["tests.system.test_a"]),
            patch.object(run_quality_gate, "SYSTEM_TIMINGS_PATH", Path(tempfile.gettempdir()) / "system-timings-fail-test.json"),
            self.assertRaisesRegex(RuntimeError, "budget exceeded"),
        ):
            run_quality_gate.run_system_tests({}, runner=lambda *args, **kwargs: None, clock=lambda: next(ticks))

    def test_system_runner_failure_is_reported_without_hiding_error(self):
        budgets = {
            "schema_version": 1,
            "modules": {"tests.system.test_a": {"warning_seconds": 2, "fail_seconds": 4}},
            "total": {"warning_seconds": 4, "fail_seconds": 5},
        }
        report_path = Path(tempfile.gettempdir()) / "system-timings-runner-fail.json"
        error = subprocess.CalledProcessError(7, ["test"])
        with (
            patch.object(run_quality_gate, "load_system_test_budgets", return_value=budgets),
            patch.object(run_quality_gate, "system_test_modules", return_value=["tests.system.test_a"]),
            patch.object(run_quality_gate, "SYSTEM_TIMINGS_PATH", report_path),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            run_quality_gate.run_system_tests({}, runner=lambda *args, **kwargs: (_ for _ in ()).throw(error), clock=iter((0, 0, 1, 1)).__next__)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["modules"][0]["test_status"], "failed")
        self.assertEqual(report["modules"][0]["status"], "failed")
        self.assertEqual(report["modules"][0]["error_type"], "CalledProcessError")
        self.assertEqual(report["modules"][0]["returncode"], 7)
        self.assertEqual(report["total"]["status"], "failed")

    def test_budget_schema_requires_exact_modules_and_ordered_thresholds(self):
        valid = {"schema_version": 1, "modules": {"tests.system.test_a": {"warning_seconds": 1, "fail_seconds": 2}}, "total": {"warning_seconds": 3, "fail_seconds": 4}}
        run_quality_gate.validate_system_test_budgets(valid, ["tests.system.test_a"])
        for invalid in (
            {"modules": {}, "total": valid["total"]},
            {"modules": {"tests.system.test_a": {"warning_seconds": 2, "fail_seconds": 2}}, "total": valid["total"]},
            {"modules": valid["modules"], "total": {"warning_seconds": 0, "fail_seconds": 4}},
            {"schema_version": 2, "modules": valid["modules"], "total": valid["total"]},
            {"schema_version": 1, "total": valid["total"]},
        ):
            with self.assertRaises(ValueError):
                run_quality_gate.validate_system_test_budgets(invalid, ["tests.system.test_a"])


if __name__ == "__main__":
    unittest.main()
