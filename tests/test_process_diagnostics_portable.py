"""A real isolated source-slice check for the diagnostics demonstration."""

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
DIAGNOSTICS_FILES = (
    "app/manufacturing/process_diagnostics/__init__.py",
    "app/manufacturing/process_diagnostics/contracts.py",
    "app/manufacturing/process_diagnostics/handler.py",
    "app/manufacturing/process_diagnostics/binding.py",
    "app/integrations/manufacturing/fake_process_diagnostics.py",
    "app/integrations/manufacturing/sqlite_process_diagnostics.py",
    "app/bootstrap/diagnostics_demo.py",
)


class ProcessDiagnosticsPortableTests(unittest.TestCase):
    def test_demo_runs_from_actual_60_file_source_slice(self) -> None:
        baseline = json.loads(INVENTORY.read_text(encoding="utf-8"))["units"][
            "dispatcher_pilot"
        ]["files"]
        files = (
            tuple(baseline)
            + RUNTIME_FILES
            + MODERN_FILES
            + READY_FILES
            + LOOP_FILES
            + DIAGNOSTICS_FILES
        )
        self.assertEqual((len(files), len(set(files))), (60, 60))
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

from app.bootstrap import diagnostics_demo
payloads = []
diagnostics_demo.print = lambda *values, **kwargs: payloads.append(values[0])
assert diagnostics_demo.main(['--mode', 'ready', '--tool', 'get_process_capability', '--arguments', '{"process_step":"CMP"}']) == 0
ready = json.loads(payloads[-1])
assert ready['typed_results'][0]['status'] == 'succeeded'
assert ready['model_tool_selection_calls'] == 0
assert ready['sources']['fake:process-diagnostics']['scope']['process_steps'] == ['CMP']
assert diagnostics_demo.main(['--mode', 'loop', '--tool', 'get_sensor_summary', '--arguments', '{"process_step":"CMP","equipment_id":"CMP-01","signal_name":"pressure"}']) == 0
loop = json.loads(payloads[-1])
assert loop['typed_results'][0]['status'] == 'succeeded'
assert loop['model_tool_selection_calls'] == 1 and loop['model_response_calls'] == 2
assert loop['observations'][0]['arguments']['process_step'] == 'CMP'
assert loop['observations'][0]['arguments']['equipment_id'] == 'CMP-01'
assert loop['observations'][0]['arguments']['signal_name'] == 'pressure'
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
