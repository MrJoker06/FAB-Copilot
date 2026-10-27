from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "evaluations" / "mod_007_dispatcher_bundle_v1.json"
RUNTIME_FILES = (
    "app/agent_runtime/execution/runtime_contracts.py",
    "app/agent_runtime/execution/runtime_ports.py",
    "app/agent_runtime/execution/pilot_stages.py",
)


class RuntimePortsPortableTests(unittest.TestCase):
    def test_runtime_ports_execute_from_explicit_mod007_source_slice(self) -> None:
        listed = json.loads(INVENTORY.read_text(encoding="utf-8"))["units"][
            "dispatcher_pilot"
        ]["files"]
        files = tuple(listed) + RUNTIME_FILES
        self.assertEqual(len(files), 40)
        self.assertEqual(len(set(files)), len(files))
        with tempfile.TemporaryDirectory() as raw:
            unit = Path(raw) / "unit"
            for relative in files:
                source, destination = ROOT / relative, unit / relative
                self.assertTrue(source.is_file(), relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            code = """import asyncio, importlib, importlib.abc, os, socket, sqlite3, sys
from datetime import date
from pathlib import Path

unit = Path(sys.argv[1]).resolve()
allowed = set(sys.argv[2:])
assert not any(str(unit) in entry for entry in sys.path)
sys.path.insert(0, str(unit))
blocked = (
    'app.core.settings', 'app.agent_runtime.tools.catalog',
    'app.agent_runtime.tools.registry', 'app.bootstrap',
    'app.model_gateway', 'app.evidence', 'app.persistence',
    'app.manufacturing.reports',
)
guard_events = []
class BlockedFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == item or fullname.startswith(item + '.') for item in blocked):
            guard_events.append(('import', fullname))
            raise AssertionError('blocked import: ' + fullname)
        return None

class DenyEnvironment(dict):
    def __getitem__(self, key):
        if key in {'PYTHONASYNCIODEBUG', 'LANG', 'LANGUAGE', 'COLUMNS', 'LINES', 'TERM'} or key.startswith('LC_'):
            return ''
        raise AssertionError('environment read: ' + key)
    def get(self, key, default=None):
        if key in {'PYTHONASYNCIODEBUG', 'LANG', 'LANGUAGE', 'COLUMNS', 'LINES', 'TERM'} or key.startswith('LC_'):
            return ''
        raise AssertionError('environment read: ' + key)
    def __iter__(self):
        raise AssertionError('environment iteration')

sys.meta_path.insert(0, BlockedFinder())
os.environ = DenyEnvironment()
os.getenv = lambda key, default=None: os.environ.get(key, default)
def audit(event, args):
    if event in {'sqlite3.connect', 'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname'}:
        guard_events.append((event, args))
        raise AssertionError(event)
sys.addaudithook(audit)
for operation in (
    lambda: importlib.import_module('app.manufacturing.reports'),
    lambda: os.environ.get('FAB_DATABASE_PATH'),
    lambda: socket.socket().connect(('127.0.0.1', 9)),
    lambda: socket.getaddrinfo('example.invalid', 443),
    lambda: sqlite3.connect(':memory:'),
):
    try:
        operation()
    except AssertionError:
        pass
    else:
        raise AssertionError('negative control did not trigger')
assert any(event == 'import' for event, _ in guard_events)
assert any(event == 'socket.connect' for event, _ in guard_events)
assert any(event == 'socket.getaddrinfo' for event, _ in guard_events)
assert any(event == 'sqlite3.connect' for event, _ in guard_events)
guard_events.clear()

from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.pilot_stages import execute_model_stage, execute_tool_stage, publish_stage_event
from app.agent_runtime.execution.runtime_contracts import ModelMessage, ModelRequest, ModelResponse, ModelToolCall, RuntimeContext
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import ToolExecutionLimits, ToolStatus
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.agent_runtime.tools.dispatcher import ToolDispatcher
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY, ToolRegistry
from app.integrations.manufacturing.fake_equipment_health import demo_fake_adapter
from app.manufacturing.equipment_health.binding import create_equipment_health_binding
from app.planning_runtime.contracts import AnalysisScopeContract, ExecutionPlan, PlanBudget

class Principal:
    tenant_id = 'tenant'
    user_id = 'user'
    roles = ('analyst',)
class Model:
    def __init__(self): self.calls = 0
    async def complete(self, request, context):
        self.calls += 1
        return ModelResponse(tool_calls=(ModelToolCall('model-id', 'get_equipment_health', '{}'),))
class Sink:
    def __init__(self): self.events = []
    async def emit(self, event): self.events.append(event)

async def main():
    plan = ExecutionPlan('portable', '1', 'test', 'ready', '', '', None, None,
        AnalysisScopeContract('equipment', (), (), ()), (), (),
        PlanBudget(1, 1, 1, 100, {'get_equipment_health': 1}, 1, 1), (), ())
    registry = ToolRegistry()
    registry.register_native(create_equipment_health_binding(
        demo_fake_adapter(demo_tenant_id='tenant', as_of=date(2026, 10, 24)),
        today=lambda: date(2026, 10, 24)))
    assert DEFAULT_TOOL_REGISTRY.model_tools == [] and DEFAULT_TOOL_REGISTRY.legacy_handlers == {}
    dispatcher = ToolDispatcher(run_id='run', registry=registry,
        policy=DemoToolPolicy(frozenset({'get_equipment_health'}), frozenset({'analyst'}), 'tenant'),
        budget=LoopGuardToolBudget(ToolLoopGuard(plan)), allowed_tools=frozenset({'get_equipment_health'}))
    context = RuntimeContext(Principal(), 'run', ToolExecutionLimits(remaining_calls=1))
    model, sink = Model(), Sink()
    model_stage = await execute_model_stage(context, ModelRequest('provider', (ModelMessage('user', 'health'),)), model=model)
    tool_stage = await execute_tool_stage(context, model_stage.value.tool_calls[0], dispatcher=dispatcher, call_id='server')
    await publish_stage_event(model_stage.event, sink=sink)
    await publish_stage_event(tool_stage.event, sink=sink)
    assert model.calls == 1 and len(sink.events) == 2
    assert tool_stage.value.status is ToolStatus.SUCCEEDED
    assert tool_stage.value.data and tool_stage.value.sources[0].scope.tenant_id == 'tenant'
    assert tool_stage.event.call_id == 'server'

asyncio.run(main())
for name, module in list(sys.modules.items()):
    if name == 'app' or name.startswith('app.'):
        origin = Path(module.__file__).resolve()
        assert origin.is_relative_to(unit), origin
        assert origin.relative_to(unit).as_posix() in allowed, origin
assert not guard_events
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
