from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.agent_runtime import assistant_capabilities
from app.agent_runtime.execution import loop_guard
from app.conversation import context_resolver, decision_arbiter, sessions, turn_decision
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
    def test_removed_conversation_facades_have_one_canonical_owner(self):
        root = Path(__file__).resolve().parents[1] / "app"
        for name in ("assistant_capabilities", "context_resolver", "decision_arbiter", "loop_guard", "sessions", "turn_decision"):
            with self.subTest(name=name):
                self.assertFalse((root / f"{name}.py").exists())
        self.assertEqual(assistant_capabilities.__name__, "app.agent_runtime.assistant_capabilities")
        self.assertEqual(context_resolver.__name__, "app.conversation.context_resolver")

    def test_canonical_exports_have_domain_owners(self):
        owners = (
            (context_resolver.ContextResolution, "app.conversation.context_resolver"),
            (context_resolver.semantic_context_resolution, "app.conversation.context_resolver"),
            (turn_decision.TurnDecision, "app.conversation.turn_decision"),
            (turn_decision.TurnDecisionValidationError, "app.conversation.turn_decision"),
            (decision_arbiter.ArbitrationResult, "app.conversation.decision_arbiter"),
            (decision_arbiter.recover_active_flow, "app.conversation.decision_arbiter"),
            (sessions.create_session, "app.conversation.sessions"),
            (sessions._scope, "app.conversation.sessions"),
            (assistant_capabilities.build_meta_response, "app.agent_runtime.assistant_capabilities"),
            (loop_guard.ToolLoopGuard, "app.agent_runtime.execution.loop_guard"),
            (loop_guard.ToolCallDecision, "app.agent_runtime.execution.loop_guard"),
        )
        for value, owner in owners:
            with self.subTest(name=getattr(value, "__name__", type(value).__name__)):
                self.assertEqual(value.__module__, owner)

    def test_guard_state_and_budget_behavior_are_shared_across_paths(self):
        guard = loop_guard.ToolLoopGuard(_plan())
        self.assertIsInstance(guard, loop_guard.ToolLoopGuard)
        self.assertTrue(guard.check_call("get_fab_overview", {}).allowed)
        self.assertFalse(loop_guard.ToolLoopGuard.check_call(guard, "get_fab_overview", {"scope": "fab"}).allowed)
        self.assertEqual(guard.total_calls, 1)
        self.assertEqual(guard.stop_reason, "total_tool_budget_exhausted")

    def test_import_orders_do_not_open_network_connections(self):
        orders = {
            "runtime_first": "import app.agent_runtime.assistant_capabilities, app.agent_runtime.execution.loop_guard; import app.conversation.context_resolver, app.conversation.turn_decision, app.conversation.decision_arbiter, app.conversation.sessions",
            "conversation_first": "import app.conversation.context_resolver, app.conversation.turn_decision, app.conversation.decision_arbiter, app.conversation.sessions; import app.agent_runtime.assistant_capabilities, app.agent_runtime.execution.loop_guard",
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
