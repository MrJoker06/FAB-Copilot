from __future__ import annotations

import inspect
import unittest

import app.planner as facade
from app.planning_runtime import service
from app.planning_runtime import contracts, queries, scope, steps


class PlanningRuntimeBoundaryTests(unittest.TestCase):
    def test_facade_keeps_contract_identity_and_private_helpers(self):
        self.assertIs(facade.ExecutionPlan, contracts.ExecutionPlan)
        self.assertIs(facade.PlanStep, contracts.PlanStep)
        self.assertIs(facade.create_execution_plan, service.create_execution_plan)
        self.assertIs(facade._ready_steps, steps._ready_steps)
        self.assertIs(facade._manufacturing_queries, queries._manufacturing_queries)
        self.assertIs(facade._analysis_scope_contract, scope._analysis_scope_contract)

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

    def test_facade_is_thin_and_runtime_uses_intent_contracts(self):
        self.assertNotIn("def create_execution_plan", inspect.getsource(facade))
        self.assertIn("intent_runtime.contracts", inspect.getsource(service))
        for module in (contracts, queries, scope, steps, service):
            self.assertNotIn("planner import", inspect.getsource(module))


if __name__ == "__main__":
    unittest.main()
