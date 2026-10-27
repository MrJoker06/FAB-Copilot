from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DispatcherBoundaryTests(unittest.TestCase):
    def test_core_dispatch_modules_are_registered_as_pure_tool_or_runtime_files(self):
        files = json.loads(
            (ROOT / "evaluations/mod_003_boundaries_v1.json").read_text()
        )["files"]
        index = {item["path"]: item for item in files}
        expected = {
            "app/agent_runtime/tools/dispatch_contracts.py": "tool_system",
            "app/agent_runtime/tools/dispatch_policy.py": "tool_system",
            "app/agent_runtime/tools/dispatcher.py": "tool_system",
            "app/agent_runtime/execution/tool_budget.py": "runtime",
            "app/agent_runtime/execution/tool_result_bridge.py": "runtime",
            "app/bootstrap/dispatcher_demo.py": "application_bootstrap",
        }
        for path, module in expected.items():
            with self.subTest(path=path):
                self.assertEqual(index[path]["primary_module"], module)
                self.assertEqual(
                    index[path]["artifact_group"],
                    "platform_core"
                    if module != "application_bootstrap"
                    else "application_bundle",
                )

    def test_dispatcher_import_isolated_from_legacy_assembly(self):
        # Isolated mode deliberately drops cwd.  The source root is supplied only
        # for this core-slice test; active guards prove that import cannot reach
        # application assembly, settings, business, database, or model code.
        code = f"""import importlib.abc
import json
import socket
import sqlite3
import sys

sys.path.insert(0, {str(ROOT)!r})
blocked = ("app.core.settings", "app.bootstrap", "app.manufacturing", "app.persistence", "app.model_gateway", "app.evidence")
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(blocked):
            raise ImportError("blocked: " + fullname)
        return None
sys.meta_path.insert(0, Guard())
socket.socket.connect = lambda *args: (_ for _ in ()).throw(AssertionError("network"))
sqlite3.connect = lambda *args: (_ for _ in ()).throw(AssertionError("database"))
import app.agent_runtime.tools.dispatcher as dispatcher
try:
    socket.socket().connect(("127.0.0.1", 1))
except AssertionError:
    socket_blocked = True
else:
    socket_blocked = False
try:
    sqlite3.connect(":memory:")
except AssertionError:
    sqlite_blocked = True
else:
    sqlite_blocked = False
try:
    import app.core.settings
except ImportError:
    negative_control = True
else:
    negative_control = False
loaded = sorted(name for name in sys.modules if name.startswith(blocked))
print(json.dumps({{"name": dispatcher.ToolDispatcher.__name__, "negative": negative_control, "loaded": loaded, "socket": socket_blocked, "sqlite": sqlite_blocked}}))
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["name"], "ToolDispatcher")
        self.assertTrue(result["negative"])
        self.assertTrue(result["socket"])
        self.assertTrue(result["sqlite"])
        self.assertEqual(result["loaded"], [])

    def test_lazy_execution_and_planning_exports_keep_order_and_identity(self):
        code = f"""import importlib
import json
import sys
sys.path.insert(0, {str(ROOT)!r})
execution = importlib.import_module("app.agent_runtime.execution")
planning = importlib.import_module("app.planning_runtime")
execution_modules = {{"AgentLoopContext": "agent_loop", "run_agent_loop": "agent_loop", "execute_ready_plan": "ready_plan", "ready_step_order": "ready_plan", "ModelFailureDecision": "failure", "decide_model_failure": "failure"}}
planning_modules = {{"ExecutionPlan": "contracts", "PlanBudget": "contracts", "PlanStep": "contracts", "create_execution_plan": "service", "planner_system_message": "service"}}
def identities(package, mapping):
    return all(getattr(package, name) is getattr(importlib.import_module(package.__name__ + "." + module), name) for name, module in mapping.items())
try:
    getattr(execution, "missing")
except AttributeError:
    execution_unknown = True
else:
    execution_unknown = False
try:
    getattr(planning, "missing")
except AttributeError:
    planning_unknown = True
else:
    planning_unknown = False
print(json.dumps({{"execution_all": execution.__all__, "planning_all": planning.__all__, "execution_identity": identities(execution, execution_modules), "planning_identity": identities(planning, planning_modules), "execution_unknown": execution_unknown, "planning_unknown": planning_unknown}}))
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(
            result["execution_all"],
            [
                "AgentLoopContext",
                "execute_ready_plan",
                "ready_step_order",
                "run_agent_loop",
                "ModelFailureDecision",
                "decide_model_failure",
            ],
        )
        self.assertEqual(
            result["planning_all"],
            [
                "ExecutionPlan",
                "PlanBudget",
                "PlanStep",
                "create_execution_plan",
                "planner_system_message",
            ],
        )
        self.assertTrue(result["execution_identity"])
        self.assertTrue(result["planning_identity"])
        self.assertTrue(result["execution_unknown"])
        self.assertTrue(result["planning_unknown"])
