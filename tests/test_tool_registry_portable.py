from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "evaluations/mod_005_equipment_health_source_v1.json"


class ToolRegistryPortableTests(unittest.TestCase):
    def test_registry_core_runs_with_the_mod005_source_inventory_only(self):
        files = json.loads(INVENTORY.read_text(encoding="utf-8"))["files"]
        files.append("app/agent_runtime/tools/tool_registry.py")
        with tempfile.TemporaryDirectory() as raw:
            unit = Path(raw) / "unit"
            for relative in files:
                destination = unit / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            code = """import builtins, os, socket, sqlite3, sys
from datetime import date
from pathlib import Path
unit = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(unit))
blocked = {'app.bootstrap','app.core.settings','app.manufacturing.reports','app.knowledge.rag','app.agent_runtime.tools.catalog','app.agent_runtime.tools.registry'}
old = builtins.__import__
def guarded(name, *args, **kwargs):
    if any(name == item or name.startswith(item + '.') for item in blocked): raise AssertionError(name)
    return old(name, *args, **kwargs)
builtins.__import__ = guarded
class DenyEnvironment(dict):
    def __getitem__(self, key): raise AssertionError('environment read')
    def get(self, key, default=None): raise AssertionError('environment read')
    def __iter__(self): raise AssertionError('environment read')
os.environ = DenyEnvironment()
os.getenv = lambda *a, **k: (_ for _ in ()).throw(AssertionError('environment read'))
socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network'))
sqlite3.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('sqlite'))
for operation in (lambda: guarded('app.bootstrap'), lambda: os.environ.get('X'), lambda: os.getenv('X'), lambda: socket.socket(), lambda: sqlite3.connect(':memory:')):
    try: operation()
    except AssertionError: pass
    else: raise AssertionError('negative control')
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY, ToolRegistry
from app.agent_runtime.tools.contracts import ToolExecutionContext, ToolStatus
from app.manufacturing.equipment_health.binding import create_equipment_health_binding
from app.integrations.manufacturing.fake_equipment_health import demo_fake_adapter
class Principal: tenant_id='tenant'; user_id='user'; roles=('analyst',)
binding = create_equipment_health_binding(demo_fake_adapter(demo_tenant_id='tenant', as_of=date(2026,10,24)), today=lambda: date(2026,10,24))
registry = ToolRegistry(); registry.register_native(binding)
assert DEFAULT_TOOL_REGISTRY.model_tools == [] and DEFAULT_TOOL_REGISTRY.legacy_handlers == {}
resolved = registry.resolve('get_equipment_health')
value = resolved.definition.parse({})
result = resolved.handler(value, ToolExecutionContext(Principal(), 'run', 'call', resolved.dependencies))
assert result.status is ToolStatus.SUCCEEDED and result.row_count == 1 and result.data and result.sources
try: registry.legacy_adapter('get_equipment_health')
except ValueError: pass
else: raise AssertionError('native had legacy adapter')
typed_calls = []; legacy_calls = []
class Failure:
    def __call__(self, input_value, context):
        typed_calls.append('typed'); raise RuntimeError('typed failure')
resolved = registry.resolve('get_equipment_health')
registry._native_bindings['get_equipment_health'] = type(resolved)(resolved.definition, Failure(), resolved.dependencies)
registry.legacy_handlers['get_equipment_health'] = lambda: legacy_calls.append('legacy')
resolved = registry.resolve('get_equipment_health')
try: resolved.handler(value, ToolExecutionContext(Principal(), 'run', 'failure', resolved.dependencies))
except RuntimeError as error: assert str(error) == 'typed failure'
else: raise AssertionError('typed failure was swallowed')
assert typed_calls == ['typed'] and legacy_calls == []
for name, module in list(sys.modules.items()):
    if name == 'app' or name.startswith('app.'):
        origin = Path(module.__file__).resolve(); assert origin.is_relative_to(unit), origin
        assert origin.relative_to(unit).as_posix() in set(sys.argv[2:]), origin
assert not any(name in sys.modules for name in blocked)
"""
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-c", code, str(unit), *files],
                cwd=unit,
                env={},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
