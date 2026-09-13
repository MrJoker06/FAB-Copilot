from __future__ import annotations

import inspect
import unittest
from datetime import date

from app.intent_runtime import contracts, routing, rules, scope, time


class IntentRuntimeBoundaryTests(unittest.TestCase):
    def test_runtime_owners_are_explicit(self):
        self.assertEqual(contracts.IntentRoute.__module__, "app.intent_runtime.contracts")
        self.assertEqual(rules.__name__, "app.intent_runtime.rules")
        self.assertEqual(routing.route_question.__module__, "app.intent_runtime.routing")
        self.assertEqual(time._time_range.__module__, "app.intent_runtime.time")
        self.assertEqual(scope._manufacturing_scope_resolution.__module__, "app.intent_runtime.scope")

    def test_runtime_has_no_retired_root_dependency(self):
        for module in (contracts, rules, scope, time, routing):
            self.assertNotIn("intent_router import", inspect.getsource(module))

    def test_date_and_rule_snapshots_remain_deterministic(self):
        self.assertEqual(
            time._time_range("最近两周", date(2026, 9, 7)).__dict__,
            {"start": "2026-08-25", "end": "2026-09-07", "source": "relative", "assumed": False},
        )
        route = routing.route_question("CMP-12A 最近7天 Cpk 漂移", date(2026, 9, 7))
        self.assertEqual((route.intent, route.process_steps, route.equipment_ids), ("capability_excursion", ("CMP",), ("CMP-12A",)))


if __name__ == "__main__":
    unittest.main()
