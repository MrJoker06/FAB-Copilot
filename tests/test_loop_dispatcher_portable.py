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
RUNTIME_FILES = (
    "app/agent_runtime/execution/runtime_contracts.py",
    "app/agent_runtime/execution/runtime_ports.py",
    "app/agent_runtime/execution/pilot_stages.py",
)
MODERN_FILES = (
    "app/agent_runtime/definition.py",
    "app/agent_runtime/application.py",
    "app/bootstrap/agent_assembly.py",
    "app/bootstrap/agent_demo.py",
)
READY_FILES = (
    "app/agent_runtime/execution/ready_graph.py",
    "app/agent_runtime/execution/ready_dispatch.py",
    "app/agent_runtime/execution/ready_result_policy.py",
    "app/bootstrap/ready_assembly.py",
    "app/bootstrap/ready_demo.py",
)
LOOP_FILES = (
    "app/agent_runtime/execution/loop_response.py",
    "app/agent_runtime/execution/loop_dispatch.py",
    "app/bootstrap/loop_assembly.py",
    "app/bootstrap/loop_demo.py",
)


class LoopDispatcherPortableTests(unittest.TestCase):
    def test_loop_demo_runs_from_actual_53_file_source_slice(self):
        baseline = json.loads(INVENTORY.read_text(encoding="utf-8"))["units"][
            "dispatcher_pilot"
        ]["files"]
        files = (
            tuple(baseline) + RUNTIME_FILES + MODERN_FILES + READY_FILES + LOOP_FILES
        )
        self.assertEqual((len(files), len(set(files))), (53, 53))
        with tempfile.TemporaryDirectory() as raw:
            unit = Path(raw) / "unit"
            for relative in files:
                source, destination = ROOT / relative, unit / relative
                self.assertTrue(source.is_file(), relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            code = r"""import importlib, importlib.abc, json, os, socket, sqlite3, sys
from pathlib import Path

unit = Path(sys.argv[1]).resolve()
allowed = set(sys.argv[2:])
assert not any(str(unit) in item for item in sys.path)
sys.path.insert(0, str(unit))
blocked = (
    'app.agent_runtime.service', 'app.agent_runtime.compatibility',
    'app.agent_runtime.execution.agent_loop', 'app.agent_runtime.tools.catalog',
    'app.agent_runtime.tools.registry', 'app.core.settings', 'app.model_gateway',
    'app.evidence', 'app.persistence', 'app.manufacturing.reports',
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

from app.bootstrap import loop_demo, ready_demo
from app.agent_runtime.execution import ready_dispatch
async def forbidden_ready(*args, **kwargs): raise AssertionError('ready dispatch must not run')
async def forbidden_ready_demo(*args, **kwargs): raise AssertionError('ready demo must not run')
ready_dispatch.execute_dispatched_ready_plan = forbidden_ready
ready_demo._run = forbidden_ready_demo
payloads = []
loop_demo.print = lambda *values, **kwargs: payloads.append(values[0])
assert loop_demo.main(['--as-of', '2026-10-24']) == 0
payload = json.loads(payloads[-1])
assert payload['model_tool_selection_calls'] == 1
assert payload['execution_mode'] == 'model_loop'
assert payload['typed_results'][0]['call_id'] == 'loop-1-1'
assert payload['trace'][0]['call_id'] == 'loop-1-1'
assert payload['trace'][0]['model_tool_call_id'] == 'model-health-1'
assert payload['guard']['total_calls'] == 1
assert not events
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
assert DEFAULT_TOOL_REGISTRY.model_tools == [] and DEFAULT_TOOL_REGISTRY.legacy_handlers == {}
for name, module in list(sys.modules.items()):
    if name == 'app' or name.startswith('app.'):
        origin = Path(module.__file__).resolve()
        assert origin.is_relative_to(unit), origin
        assert origin.relative_to(unit).as_posix() in allowed, origin
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
