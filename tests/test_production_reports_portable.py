"""Run the production-report demonstration from the real 69-file source slice."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_process_diagnostics_portable import (
    DIAGNOSTICS_FILES,
    INVENTORY,
    LOOP_FILES,
    MODERN_FILES,
    READY_FILES,
    ROOT,
    RUNTIME_FILES,
)

PRODUCTION_FILES = (
    "app/manufacturing/production_reports/__init__.py",
    "app/manufacturing/production_reports/contracts.py",
    "app/manufacturing/production_reports/handler.py",
    "app/manufacturing/production_reports/binding.py",
    "app/integrations/manufacturing/fake_production_reports.py",
    "app/integrations/manufacturing/sqlite_production_reports.py",
    "app/bootstrap/production_reports_demo.py",
)


class ProductionReportsPortableTests(unittest.TestCase):
    def test_all_fake_reports_run_from_the_actual_69_file_slice(self) -> None:
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
            + PRODUCTION_FILES
        )
        self.assertEqual((len(files), len(set(files))), (69, 69))
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
assert not any(str(unit) in value for value in sys.path)
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

from app.bootstrap import production_reports_demo
payloads = []
production_reports_demo.print = lambda *values, **kwargs: payloads.append(values[0])
cases = (
    ('get_fab_overview', '{}', 'fab_overview'),
    ('get_yield_trend', '{"product":"P1"}', 'weekly_yield'),
    ('get_process_pass_rate', '{"process_step":"CMP"}', 'process_pass_rate'),
)
for tool, arguments, grain in cases:
    assert production_reports_demo.main(['--mode', 'ready', '--tool', tool, '--arguments', arguments]) == 0
    ready = json.loads(payloads[-1])
    assert ready['typed_results'][0]['status'] == 'succeeded'
    assert ready['model_tool_selection_calls'] == 0
    assert ready['sources']['fake:production-reports']['scope']['grain'] == grain
    assert production_reports_demo.main(['--mode', 'loop', '--tool', tool, '--arguments', arguments]) == 0
    loop = json.loads(payloads[-1])
    assert loop['typed_results'][0]['status'] == 'succeeded'
    assert loop['model_tool_selection_calls'] == 1 and loop['model_response_calls'] == 2
    assert loop['observations'][0]['source_ref'] == 'TOOL:S01'
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
