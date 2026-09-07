from __future__ import annotations

import inspect
import unittest
from datetime import date

import app.intent_router as facade
from app.intent_runtime import contracts, routing, rules, scope, time


class IntentRuntimeBoundaryTests(unittest.TestCase):
    def test_facade_preserves_public_and_private_object_identity(self):
        self.assertIs(facade.IntentRoute, contracts.IntentRoute)
        self.assertIs(facade.INTENT_LABELS, rules.INTENT_LABELS)
        self.assertIs(facade.route_question, routing.route_question)
        self.assertIs(facade._time_range, time._time_range)
        self.assertIs(facade._manufacturing_scope_resolution, scope._manufacturing_scope_resolution)

    def test_runtime_does_not_depend_on_facade_and_facade_stays_thin(self):
        for module in (contracts, rules, scope, time, routing):
            self.assertNotIn("intent_router import", inspect.getsource(module))
        self.assertNotIn("def route_question", inspect.getsource(facade))

    def test_date_and_rule_snapshots_remain_deterministic(self):
        self.assertEqual(
            facade._time_range("最近两周", date(2026, 9, 7)).__dict__,
            {"start": "2026-08-25", "end": "2026-09-07", "source": "relative", "assumed": False},
        )
        route = facade.route_question("CMP-12A 最近7天 Cpk 漂移", date(2026, 9, 7))
        self.assertEqual((route.intent, route.process_steps, route.equipment_ids), ("capability_excursion", ("CMP",), ("CMP-12A",)))


if __name__ == "__main__":
    unittest.main()
