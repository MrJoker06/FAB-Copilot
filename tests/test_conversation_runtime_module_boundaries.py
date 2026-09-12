from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app import assistant_capabilities, context_resolver, decision_arbiter, loop_guard, sessions, turn_decision
from app.agent_runtime import assistant_capabilities as canonical_capabilities
from app.agent_runtime.execution import loop_guard as canonical_guard
from app.conversation import context_resolver as canonical_context
from app.conversation import decision_arbiter as canonical_arbiter
from app.conversation import sessions as canonical_sessions
from app.conversation import turn_decision as canonical_decision
from app.planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
)
from scripts.check_module_boundaries import boundary_errors, load_manifest


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="boundary", schema_version="1", planner_version="test", status="ready",
        reason="", route_intent="fab_overview", playbook_id=None, playbook_version=None,
        scope_contract=AnalysisScopeContract("fab", (), (), ()), required_evidence_ids=(), steps=(),
        budget=PlanBudget(1, 1, 1, 10, {"get_fab_overview": 1}, 1, 1), missing_inputs=(),
        clarification_questions=(),
    )


class ConversationRuntimeModuleBoundaryTests(unittest.TestCase):
    def test_legacy_capability_facade_is_import_only_and_has_no_side_effect_body(self):
        source = Path(assistant_capabilities.__file__).read_text(encoding="utf-8")
        module = ast.parse(source)
        self.assertEqual(ast.get_docstring(module), "Compatibility facade for :mod:`app.agent_runtime.assistant_capabilities`.")
        expected = ast.parse(
            "from __future__ import annotations\n"
            "from .agent_runtime import assistant_capabilities as _canonical\n"
            "from .agent_runtime.assistant_capabilities import *\n"
            "def __getattr__(name: str):\n"
            "    return getattr(_canonical, name)\n"
        )
        actual = ast.Module(body=module.body[1:], type_ignores=[])
        self.assertEqual(ast.dump(actual), ast.dump(expected))

    def test_legacy_facades_share_canonical_public_types_functions_and_helpers(self):
        pairs = (
            (context_resolver.ContextResolution, canonical_context.ContextResolution),
            (context_resolver.semantic_context_resolution, canonical_context.semantic_context_resolution),
            (turn_decision.TurnDecision, canonical_decision.TurnDecision),
            (turn_decision.TurnDecisionValidationError, canonical_decision.TurnDecisionValidationError),
            (decision_arbiter.ArbitrationResult, canonical_arbiter.ArbitrationResult),
            (decision_arbiter.recover_active_flow, canonical_arbiter.recover_active_flow),
            (sessions.create_session, canonical_sessions.create_session),
            (sessions._scope, canonical_sessions._scope),
            (assistant_capabilities.CAPABILITIES, canonical_capabilities.CAPABILITIES),
            (assistant_capabilities.build_meta_response, canonical_capabilities.build_meta_response),
            (loop_guard.ToolLoopGuard, canonical_guard.ToolLoopGuard),
            (loop_guard.ToolCallDecision, canonical_guard.ToolCallDecision),
        )
        for legacy, canonical in pairs:
            with self.subTest(name=getattr(canonical, "__name__", type(canonical).__name__)):
                self.assertIs(legacy, canonical)

    def test_guard_state_and_budget_behavior_are_shared_across_paths(self):
        guard = loop_guard.ToolLoopGuard(_plan())
        self.assertIsInstance(guard, canonical_guard.ToolLoopGuard)
        self.assertTrue(guard.check_call("get_fab_overview", {}).allowed)
        self.assertFalse(canonical_guard.ToolLoopGuard.check_call(guard, "get_fab_overview", {"scope": "fab"}).allowed)
        self.assertEqual(guard.total_calls, 1)
        self.assertEqual(guard.stop_reason, "total_tool_budget_exhausted")

    def test_import_orders_do_not_open_network_connections(self):
        orders = {
            "legacy_first": "import app.context_resolver, app.turn_decision, app.decision_arbiter, app.sessions, app.assistant_capabilities, app.loop_guard; import app.conversation.context_resolver, app.conversation.turn_decision, app.conversation.decision_arbiter, app.conversation.sessions, app.agent_runtime.assistant_capabilities, app.agent_runtime.execution.loop_guard",
            "canonical_first": "import app.conversation.context_resolver, app.conversation.turn_decision, app.conversation.decision_arbiter, app.conversation.sessions, app.agent_runtime.assistant_capabilities, app.agent_runtime.execution.loop_guard; import app.context_resolver, app.turn_decision, app.decision_arbiter, app.sessions, app.assistant_capabilities, app.loop_guard",
        }
        guard = "import socket; socket.socket.connect=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network during import')); "
        for name, imports in orders.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [sys.executable, "-c", guard + imports + "; print('import-ok')"],
                    capture_output=True, text=True, check=False,
                    env={**os.environ, "AGENT_LOG_PATH": f"{directory}/events.jsonl", "AGENT_RUN_LOG_DIR": f"{directory}/runs"},
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "import-ok")

    def test_new_canonical_pure_modules_reject_network_imports(self):
        import shutil

        with tempfile.TemporaryDirectory() as temporary:
            copied_app = Path(temporary) / "app"
            shutil.copytree(Path(__file__).resolve().parents[1] / "app", copied_app)
            target = copied_app / "conversation" / "turn_decision.py"
            target.write_text(target.read_text(encoding="utf-8") + "\nimport socket\n", encoding="utf-8")
            errors = boundary_errors(copied_app, load_manifest())
        self.assertTrue(any("app.conversation.turn_decision" in error and "pure module imports forbidden socket" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
