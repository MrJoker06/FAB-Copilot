from __future__ import annotations

import inspect
import unittest

from app.planning_runtime import service
from app.planning_runtime import contracts, queries, scope, steps


class PlanningRuntimeBoundaryTests(unittest.TestCase):
    def test_service_uses_contract_and_helper_owners(self):
        source = inspect.getsource(service)
        self.assertIn("from .contracts import ExecutionPlan, PlanBudget", source)
        self.assertIn("from .queries import _resolved_inputs", source)
        self.assertIn("from .scope import _analysis_scope_contract", source)
        self.assertIn("from .steps import _empty_budget, _generic_budget, _ready_steps", source)

    def test_implementation_ownership_has_no_service_backedges(self):
        self.assertEqual(contracts.AnalysisScopeContract.__module__, "app.planning_runtime.contracts")
        self.assertEqual(contracts.ExecutionPlan.__module__, "app.planning_runtime.contracts")
        self.assertEqual(contracts.PlanBudget.__module__, "app.planning_runtime.contracts")
        self.assertEqual(contracts.PlanStep.__module__, "app.planning_runtime.contracts")
        self.assertEqual(queries._manufacturing_queries.__module__, "app.planning_runtime.queries")
        self.assertEqual(scope._analysis_scope_contract.__module__, "app.planning_runtime.scope")
        self.assertEqual(scope._step_scope.__module__, "app.planning_runtime.scope")
        self.assertEqual(steps._ready_steps.__module__, "app.planning_runtime.steps")
        self.assertEqual(steps._tool_invocations.__module__, "app.planning_runtime.steps")
        self.assertEqual(service.create_execution_plan.__module__, "app.planning_runtime.service")
        for module in (contracts, queries, scope, steps):
            self.assertNotIn("from .service import", inspect.getsource(module))
        source = inspect.getsource(service)
        for name in ("_manufacturing_queries", "_analysis_scope_contract", "_ready_steps"):
            self.assertNotIn(f"def {name}", source)

    def test_service_uses_intent_contracts_without_retired_planner(self):
        self.assertIn("intent_runtime.contracts", inspect.getsource(service))
        for module in (contracts, queries, scope, steps, service):
            self.assertNotIn("planner import", inspect.getsource(module))


if __name__ == "__main__":
    unittest.main()
