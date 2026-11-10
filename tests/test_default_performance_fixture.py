"""Focused checks for the MOD-008 default-native performance fixture."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "mod_008_default_performance.py"
)
_SPEC = importlib.util.spec_from_file_location("mod008_default_performance", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
performance = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = performance
_SPEC.loader.exec_module(performance)


class DefaultPerformanceFixtureTests(unittest.TestCase):
    def test_formal_sampling_is_frozen_and_observation_has_minimum(self) -> None:
        performance._require_sampling(1000, 2, True)
        performance._require_sampling(50, 1, False)
        with self.assertRaises(ValueError):
            performance._require_sampling(50, 1, True)
        with self.assertRaises(ValueError):
            performance._require_sampling(30, 1, False)

    def test_current_fixture_uses_native_capabilities_and_fixed_evidence(self) -> None:
        for scene in performance.SCENES:
            with self.subTest(scene=scene):
                proof = performance._current_operation(scene)
                self.assertEqual(proof["tools"], performance.EXPECTED_TOOLS[scene])
                self.assertEqual(proof["guard_calls"], len(proof["tools"]))
                self.assertEqual(proof["audit"], {"socket": 0, "dns": 0, "sqlite": 0})
                self.assertEqual(proof["fixture"], "current-whole-service")
                self.assertEqual(
                    proof["model_calls"], 2 if scene == "loop_success" else 1
                )

    def test_source_injection_is_restored_after_fixture_run(self) -> None:
        from app.tools.operational_reports import data_source as sqlite_operational_reports
        from app.tools.knowledge_search import runtime_search

        operational = sqlite_operational_reports.SQLiteOperationalReportsAdapter
        knowledge = runtime_search.create_runtime_knowledge_port
        performance._current_operation("loop_success")
        self.assertIs(
            sqlite_operational_reports.SQLiteOperationalReportsAdapter, operational
        )
        self.assertIs(runtime_search.create_runtime_knowledge_port, knowledge)


if __name__ == "__main__":
    unittest.main()
