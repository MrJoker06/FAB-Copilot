from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "evaluations/mod_007_dispatcher_bundle_v1.json"
MODERN_FILES = (
    "app/agent_runtime/definition.py",
    "app/agent_runtime/application.py",
    "app/bootstrap/agent_assembly.py",
    "app/bootstrap/agent_demo.py",
)
RUNTIME_FILES = (
    "app/agent_runtime/execution/runtime_contracts.py",
    "app/agent_runtime/execution/runtime_ports.py",
    "app/agent_runtime/execution/pilot_stages.py",
)


class AgentAssemblyPortableTests(unittest.TestCase):
    def test_explicit_agent_assembly_runs_from_the_actual_44_file_slice(self):
        baseline = json.loads(INVENTORY.read_text(encoding="utf-8"))["units"][
            "dispatcher_pilot"
        ]["files"]
        files = tuple(baseline) + RUNTIME_FILES + MODERN_FILES
        self.assertEqual(len(files), 44)
        self.assertEqual(len(set(files)), len(files))
        with tempfile.TemporaryDirectory() as raw:
            unit = Path(raw) / "unit"
            for relative in files:
                source, destination = ROOT / relative, unit / relative
                self.assertTrue(source.is_file(), relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            code = r"""import asyncio, importlib, importlib.abc, os, socket, sqlite3, sys
from datetime import date
from pathlib import Path

unit = Path(sys.argv[1]).resolve()
allowed = set(sys.argv[2:])
assert not any(str(unit) in entry for entry in sys.path)
sys.path.insert(0, str(unit))
blocked = (
    'app.agent_runtime.service', 'app.agent_runtime.compatibility',
    'app.agent_runtime.tools.catalog', 'app.agent_runtime.tools.registry',
    'app.core.settings', 'app.bootstrap.legacy_agent_assembly',
    'app.model_gateway', 'app.evidence', 'app.persistence', 'app.manufacturing.reports',
)
events = []
class BlockedFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + '.') for item in blocked):
            events.append(('import', fullname)); raise AssertionError(fullname)
        return None
class DenyEnvironment(dict):
    def __getitem__(self, key):
        if key in {'PYTHONASYNCIODEBUG', 'LANG', 'LANGUAGE', 'COLUMNS', 'LINES', 'TERM'} or key.startswith('LC_'): return ''
        raise AssertionError('environment read: ' + key)
    def get(self, key, default=None): return self[key]
    def __iter__(self): raise AssertionError('environment iteration')
sys.meta_path.insert(0, BlockedFinder())
os.environ = DenyEnvironment()
os.getenv = lambda key, default=None: os.environ.get(key, default)
def audit(event, args):
    if event in {'sqlite3.connect', 'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname'}:
        events.append((event, args)); raise AssertionError(event)
sys.addaudithook(audit)
for operation in (
    lambda: importlib.import_module('app.agent_runtime.service'),
    lambda: os.environ.get('FAB_DATABASE_PATH'),
    lambda: socket.socket().connect(('127.0.0.1', 9)),
    lambda: socket.getaddrinfo('example.invalid', 443),
    lambda: sqlite3.connect(':memory:'),
):
    try: operation()
    except AssertionError: pass
    else: raise AssertionError('negative control')
assert any(event == 'import' for event, _ in events)
assert any(event == 'socket.connect' for event, _ in events)
assert any(event == 'socket.getaddrinfo' for event, _ in events)
assert any(event == 'sqlite3.connect' for event, _ in events)
events.clear()

from app.agent_runtime.definition import AgentDefinition, ComponentReference
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.runtime_contracts import ModelMessage, ModelResponse, ModelToolCall, RuntimeContext
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import ToolExecutionLimits, ToolStatus
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.bootstrap.agent_assembly import assemble_agent
from app.integrations.manufacturing.fake_equipment_health import demo_fake_adapter
from app.manufacturing.equipment_health.binding import create_equipment_health_binding
from app.planning_runtime.contracts import AnalysisScopeContract, ExecutionPlan, PlanBudget

class Principal:
    tenant_id = 'demo'; user_id = 'portable'; roles = ('analyst',)
class Model:
    def __init__(self): self.requests = []
    async def complete(self, request, context):
        self.requests.append(request)
        return ModelResponse(tool_calls=(ModelToolCall('provider', 'get_equipment_health', '{}'),))
class Sink:
    def __init__(self): self.events = []
    async def emit(self, event): self.events.append(event)
def plan():
    return ExecutionPlan('portable', '1', 'test', 'ready', '', '', None, None,
        AnalysisScopeContract('equipment', (), (), ()), (), (),
        PlanBudget(1, 1, 1, 100, {'get_equipment_health': 1}, 1, 1), (), ())
definition = AgentDefinition('portable-agent', '1.0.0', 'analyst', 'health only',
    (ComponentReference('get_equipment_health', '1.0.0'),),
    ComponentReference('model', '1.0.0'), ComponentReference('policy', '1.0.0'))
model, sink = Model(), Sink()
app = assemble_agent(definition, model=model, events=sink,
    bindings=(create_equipment_health_binding(demo_fake_adapter(demo_tenant_id='demo', as_of=date(2026, 10, 24)), today=lambda: date(2026, 10, 24)),),
    policy=DemoToolPolicy(frozenset({'get_equipment_health'}), frozenset({'analyst'}), 'demo'),
    budget_factory=lambda: LoopGuardToolBudget(ToolLoopGuard(plan())),
    server_capabilities=frozenset({'get_equipment_health'}),
    model_policy_ref=ComponentReference('model', '1.0.0'), policy_ref=ComponentReference('policy', '1.0.0'))
async def main():
    run = app.new_run(RuntimeContext(Principal(), 'portable-run', ToolExecutionLimits(remaining_calls=1)))
    stage = await run.model_stage(call_id='server-model', messages=(ModelMessage('user', 'health'),))
    tool = await run.tool_stage(stage.value.tool_calls[0], call_id='server-tool')
    await run.publish(stage.event); await run.publish(tool.event)
    assert model.requests[0].messages[0].role == 'system'
    assert tool.value.status is ToolStatus.SUCCEEDED and tool.value.data and tool.value.sources
    assert len(sink.events) == 2 and sink.events[-1].call_id == 'server-tool'
asyncio.run(main())
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
assert DEFAULT_TOOL_REGISTRY.model_tools == [] and DEFAULT_TOOL_REGISTRY.legacy_handlers == {}
for name, module in list(sys.modules.items()):
    if name == 'app' or name.startswith('app.'):
        origin = Path(module.__file__).resolve()
        assert origin.is_relative_to(unit), origin
        assert origin.relative_to(unit).as_posix() in allowed, origin
assert not events
assert not any(name == item or name.startswith(item + '.') for name in sys.modules for item in blocked)
"""
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-c", code, str(unit), *files],
                cwd=Path(tempfile.gettempdir()),
                env={},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
