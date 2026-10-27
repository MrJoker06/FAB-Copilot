from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.modularization_fixture_clock import (
    CAPTURE_ENVIRONMENT_DATE,
    fixed_capture_clock,
)

SPEC = importlib.util.spec_from_file_location(
    "modularization_baseline_clock_test",
    Path(__file__).resolve().parents[1] / "scripts" / "modularization_baseline.py",
)
baseline = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(baseline)


class FixtureClockTests(unittest.TestCase):
    def setUp(self):
        self.service = importlib.import_module("app.agent_runtime.service")
        self.routing = importlib.import_module("app.intent_runtime.routing")

    def test_context_replaces_only_banner_date_and_restores_modules(self):
        prompt = "before\\n当前日期是 2099-01-01。用户说：body\\nafter"
        original_date = self.routing.date
        with patch.object(self.service, "SYSTEM_PROMPT", prompt):
            with fixed_capture_clock():
                self.assertEqual(
                    "before\\n当前日期是 2026-10-22。用户说：body\\nafter",
                    self.service.SYSTEM_PROMPT,
                )
                self.assertEqual(CAPTURE_ENVIRONMENT_DATE, self.routing.date.today())
            self.assertEqual(prompt, self.service.SYSTEM_PROMPT)
            self.assertIs(original_date, self.routing.date)

    def test_context_handles_host_date_after_frozen_capture_date(self):
        prompt = "当前日期是 2026-10-24。用户说：test"
        with patch.object(self.service, "SYSTEM_PROMPT", prompt), fixed_capture_clock():
            self.assertIn("当前日期是 2026-10-22。用户说", self.service.SYSTEM_PROMPT)

    def test_context_fails_closed_for_missing_or_multiple_banners(self):
        for prompt in (
            "no capture date banner",
            "当前日期是 2026-10-24。用户说 one；当前日期是 2026-10-24。用户说 two",
        ):
            with (
                self.subTest(prompt=prompt),
                patch.object(self.service, "SYSTEM_PROMPT", prompt),
                self.assertRaisesRegex(RuntimeError, "exactly one date banner"),
                fixed_capture_clock(),
            ):
                pass

    def test_routing_default_date_is_fixed_only_inside_context(self):
        original_date = self.routing.date
        with fixed_capture_clock():
            routed = self.routing.route_question("最近 1 天 CMP")
            self.assertEqual(CAPTURE_ENVIRONMENT_DATE, self.routing.date.today())
            self.assertEqual("2026-10-22", routed.time_range.start)
            self.assertEqual("2026-10-22", routed.time_range.end)
        self.assertIs(original_date, self.routing.date)

    def test_collect_behavior_retains_non_date_prompt_drift(self):
        expected = baseline.collect_behavior()
        prompt = self.service.SYSTEM_PROMPT.replace("规则：", "规则（已漂移）：", 1)
        with patch.object(self.service, "SYSTEM_PROMPT", prompt):
            actual = baseline.collect_behavior()
        self.assertIn(
            "规则（已漂移）：", baseline.diff(expected, actual, "behavior.json")
        )

    def test_collect_behavior_matches_frozen_baseline_for_host_prompt_dates(self):
        expected = baseline.load_json(baseline.DEFAULT_BEHAVIOR)
        for host_date in ("2026-10-24", "2099-01-01"):
            prompt = _replace_banner_date(self.service.SYSTEM_PROMPT, host_date)
            with (
                self.subTest(host_date=host_date),
                patch.object(self.service, "SYSTEM_PROMPT", prompt),
            ):
                actual = baseline.collect_behavior()
            self.assertEqual("", baseline.diff(expected, actual, "behavior.json"))

    def test_baseline_help_runs_outside_project_without_pythonpath(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "modularization_baseline.py"
        )
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", str(script), "--help"],
                cwd=directory,
                env=environment,
                capture_output=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("usage:", result.stdout)


def _replace_banner_date(prompt: str, replacement: str) -> str:
    start = prompt.index("当前日期是 ") + len("当前日期是 ")
    return prompt[:start] + replacement + prompt[start + len("YYYY-MM-DD") :]


if __name__ == "__main__":
    unittest.main()
