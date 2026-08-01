from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from scripts import run_quality_gate


class QualityGateTests(unittest.TestCase):
    def test_command_sets_keep_full_suite_and_quick_excludes_system(self):
        quick = run_quality_gate.quality_commands("quick")
        full = run_quality_gate.quality_commands("full")
        self.assertIn("tests.test_quality_gate", quick[0])
        self.assertNotIn("tests.test_system", quick[0])
        self.assertIn([sys.executable, "-m", "coverage", "run", "--branch", "--source=app", "-m", "unittest", "discover", "-s", "tests"], full)
        self.assertEqual(quick[-1], [sys.executable, "scripts/evaluate_rag.py"])

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
        self.assertGreaterEqual(run_quality_gate.MIN_PYTHON_TESTS, 170)


if __name__ == "__main__":
    unittest.main()
