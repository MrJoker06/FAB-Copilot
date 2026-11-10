"""Portable, source-closed acceptance for the lithography Cpk Skill pilot."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# This is a finite source slice, not a copied ``app`` tree.  The list includes
# every module in the real Ready/Loop demo's static import closure and package
# initializers that Python imports while resolving it.
SOURCE_FILES = (
    "app/__init__.py",
    "app/agent_runtime/__init__.py",
    "app/agent_runtime/application.py",
    "app/agent_runtime/contracts.py",
    "app/agent_runtime/coordinator.py",
    "app/agent_runtime/coordinator_state.py",
    "app/agent_runtime/dependencies.py",
    "app/agent_runtime/definition.py",
    "app/agent_runtime/execution/__init__.py",
    "app/agent_runtime/execution/loop_dispatch.py",
    "app/agent_runtime/execution/loop_guard.py",
    "app/agent_runtime/execution/loop_response.py",
    "app/agent_runtime/execution/pilot_stages.py",
    "app/agent_runtime/execution/ready_dispatch.py",
    "app/agent_runtime/execution/ready_graph.py",
    "app/agent_runtime/execution/ready_result_policy.py",
    "app/agent_runtime/execution/runtime_contracts.py",
    "app/agent_runtime/execution/runtime_ports.py",
    "app/agent_runtime/execution/tool_budget.py",
    "app/agent_runtime/execution/tool_result_bridge.py",
    "app/agent_runtime/tools/__init__.py",
    "app/agent_runtime/tools/contracts.py",
    "app/agent_runtime/tools/definition.py",
    "app/agent_runtime/tools/dispatch_contracts.py",
    "app/agent_runtime/tools/dispatch_policy.py",
    "app/agent_runtime/tools/dispatcher.py",
    "app/agent_runtime/tools/projection.py",
    "app/agent_runtime/tools/tool_registry.py",
    "app/agent_runtime/stages/__init__.py",
    "app/agent_runtime/stages/availability.py",
    "app/agent_runtime/stages/loop.py",
    "app/agent_runtime/stages/model.py",
    "app/agent_runtime/stages/prepare.py",
    "app/agent_runtime/stages/ready.py",
    "app/bootstrap/__init__.py",
    "app/bootstrap/agent_assembly.py",
    "app/bootstrap/litho_cpk_demo.py",
    "app/bootstrap/litho_cpk_workflow.py",
    "app/bootstrap/loop_assembly.py",
    "app/bootstrap/ready_assembly.py",
    "app/bootstrap/skill_assembly.py",
    "app/core/__init__.py",
    "app/core/call_scope.py",
    "app/core/tool_result_projection.py",
    "app/evidence/__init__.py",
    "app/evidence/evidence_truncation.py",
    "app/evidence/semantics.py",
    "app/evidence/serialization.py",
    "app/evidence/skill_policy.py",
    "app/evidence/validator.py",
    "app/integrations/__init__.py",
    "app/integrations/knowledge/__init__.py",
    "app/demo_data/tool_sources/knowledge_search.py",
    "app/integrations/manufacturing/__init__.py",
    "app/demo_data/tool_sources/operational_reports.py",
    "app/demo_data/tool_sources/process_diagnostics.py",
    "app/intent_runtime/__init__.py",
    "app/intent_runtime/contracts.py",
    "app/intent_runtime/routing.py",
    "app/intent_runtime/rules.py",
    "app/intent_runtime/scope.py",
    "app/intent_runtime/time.py",
    "app/knowledge/__init__.py",
    "app/knowledge/decision.py",
    "app/knowledge/ranking.py",
    "app/knowledge/search_contracts.py",
    "app/knowledge/search_policy.py",
    "app/knowledge/search_query.py",
    "app/tools/knowledge_search/__init__.py",
    "app/tools/knowledge_search/binding.py",
    "app/tools/knowledge_search/contracts.py",
    "app/tools/knowledge_search/handler.py",
    "app/manufacturing/__init__.py",
    "app/manufacturing/named_playbooks.py",
    "app/tools/operational_reports/__init__.py",
    "app/tools/operational_reports/binding.py",
    "app/tools/operational_reports/contracts.py",
    "app/tools/operational_reports/handler.py",
    "app/manufacturing/playbooks.py",
    "app/tools/process_diagnostics/__init__.py",
    "app/tools/process_diagnostics/binding.py",
    "app/tools/process_diagnostics/contracts.py",
    "app/tools/process_diagnostics/handler.py",
    "app/manufacturing/processes.py",
    "app/planning_runtime/__init__.py",
    "app/planning_runtime/contracts.py",
    "app/planning_runtime/named_planner.py",
    "app/planning_runtime/queries.py",
    "app/planning_runtime/scope.py",
    "app/planning_runtime/service.py",
    "app/planning_runtime/steps.py",
    "app/skills/__init__.py",
    "app/skills/catalog.py",
    "app/skills/contracts.py",
    "app/skills/discovery.py",
    "app/skills/frontmatter.py",
    "app/skills/loader.py",
    "app/skills/manifest.py",
    "app/skills/package.py",
    "app/skills/resources.py",
    "app/skills/versions.py",
    "app/tools/__init__.py",
    "app/tools/capability_trend/__init__.py",
    "app/tools/capability_trend/contracts.py",
    "app/demo_data/tool_sources/capability_trend.py",
    "app/tools/capability_trend/tool.py",
    "app/demo_data/__init__.py",
    "app/demo_data/tool_sources/__init__.py",
)
SKILL_ASSETS = (
    "manifest.json",
    "SKILL.md",
    "references/cpk_context.md",
    "scenarios/acceptance.json",
)


class LithoCpkPortableTests(unittest.TestCase):
    def test_real_skill_ready_and_loop_run_from_explicit_isolated_slice(self) -> None:
        self.assertEqual(len(SOURCE_FILES), len(set(SOURCE_FILES)))
        with tempfile.TemporaryDirectory() as temporary:
            unit = Path(temporary) / "unit"
            for relative in SOURCE_FILES:
                source, destination = ROOT / relative, unit / relative
                self.assertTrue(source.is_file(), relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            copied_assets = unit / "skill_assets/litho-cpk-diagnostic"
            for relative in SKILL_ASSETS:
                source = ROOT / "app/skills/litho-cpk-diagnostic" / relative
                destination = copied_assets / relative
                self.assertTrue(source.is_file(), relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            code = r"""
import asyncio, importlib, importlib.abc, inspect, json, os, socket, sqlite3, subprocess, sys
from pathlib import Path
unit, asset_root = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
stdlib_asyncio = (Path(sys.base_prefix) / 'Lib' / 'asyncio').resolve()
allowed = set(sys.argv[3:]); assert not any(str(unit) in entry for entry in sys.path)
sys.path.insert(0, str(unit))
# Windows creates its event-loop self-pipe lazily.  Do it before the system
# guard, so the guard still prohibits activity from the application itself.
warm_loop = asyncio.new_event_loop(); warm_loop.close()
blocked = ('app.agent_runtime.service', 'app.agent_runtime.compatibility',
 'app.agent_runtime.execution.agent_loop', 'app.agent_runtime.tools.catalog',
 'app.agent_runtime.execution.loop_answer', 'app.agent_runtime.execution.loop_model_call', 'app.agent_runtime.execution.loop_request',
 'app.agent_runtime.execution.loop_round_validation', 'app.agent_runtime.execution.loop_state', 'app.agent_runtime.execution.loop_tool_round',
 'app.agent_runtime.tools.registry', 'app.model_gateway', 'app.persistence',
 'app.telemetry', 'app.conversation')
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
 def __contains__(self, key): raise AssertionError('environment contains: ' + key)
 def keys(self): raise AssertionError('environment keys')
 def items(self): raise AssertionError('environment items')
 def values(self): raise AssertionError('environment values')
 def copy(self): raise AssertionError('environment copy')
 def update(self, *args, **kwargs): raise AssertionError('environment update')
 def __setitem__(self, key, value): raise AssertionError('environment write: ' + key)
sys.meta_path.insert(0, BlockedFinder()); os.environ = DenyEnvironment()
os.getenv = lambda key, default=None: os.environ.get(key, default)
def audit(event, args):
 if event in {'sqlite3.connect', 'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname', 'subprocess.Popen', 'os.system'}:
  # A Windows Proactor loop creates a loopback socketpair in exactly this
  # stdlib self-pipe method.  This is the sole exception; an application call
  # made from an asyncio coroutine must still reach the rejection below.
  target = args[1] if len(args) > 1 else ()
  if (event == 'socket.connect' and os.name == 'nt' and isinstance(target, tuple)
      and target and target[0] == '127.0.0.1' and any(
       frame.function == '_make_self_pipe'
       and Path(frame.filename).resolve().is_relative_to(stdlib_asyncio)
       and frame.filename.replace('\\', '/').endswith('/asyncio/proactor_events.py')
       for frame in inspect.stack())): return
  events.append((event, args)); raise AssertionError(event)
sys.addaudithook(audit)
for operation in (lambda: importlib.import_module('app.agent_runtime.service'),
 lambda: os.environ.get('FAB_DATABASE_PATH'), lambda: socket.socket().connect(('127.0.0.1', 9)),
 lambda: socket.getaddrinfo('example.invalid', 443), lambda: sqlite3.connect(':memory:'),
 lambda: subprocess.Popen(('python', '-c', 'pass')), lambda: os.system('exit 0')):
 try: operation()
 except AssertionError: pass
 else: raise AssertionError('negative control')
assert {event for event, _ in events} >= {'import', 'socket.connect', 'socket.getaddrinfo', 'sqlite3.connect', 'subprocess.Popen', 'os.system'}
async def async_network_negative_control():
 socket.socket().connect(('127.0.0.1', 9))
try: asyncio.run(async_network_negative_control())
except AssertionError: pass
else: raise AssertionError('async socket control')
events.clear()
from app.bootstrap.litho_cpk_demo import run_litho_cpk_demo_sync
for mode, calls in (('ready', 0), ('loop', 2)):
 result = run_litho_cpk_demo_sync(mode, package_root=str(asset_root))
 assert [item['status'] for item in result['trace']] == ['ok'] * 5
 assert result['validation'].status == 'validated' and result['validation'].validator_version == '1.3.0'
 assert result['plan'].playbook_id == 'PB-CAPABILITY-001' and result['model_calls'] == calls
 assert result['metadata']['skill_id'] == 'litho-cpk-diagnostic'
 assert result['metadata']['evidence_policy_version'] == '1.3.0'
 assert 'SKILL.md' in result['metadata']['loaded_resources']
viewer = run_litho_cpk_demo_sync('ready', role='viewer', package_root=str(asset_root))
assert [item['status'] for item in viewer['trace']] == ['blocked'] * 5
assert viewer['source_calls'] == {'process_diagnostics': 0, 'operational_reports': 0, 'knowledge_search': 0, 'capability_trend': 0}
import app.bootstrap.litho_cpk_demo as demo
def forbidden_fetch(*args, **kwargs): raise AssertionError('invalid package fetched fixture data')
demo.FakeProcessDiagnosticsAdapter.fetch = forbidden_fetch
demo.FakeOperationalReportsAdapter.fetch = forbidden_fetch
demo.FakeKnowledgeSearchAdapter.fetch = forbidden_fetch
demo.FakeCapabilityTrendSource.fetch = forbidden_fetch
import shutil
missing = unit / 'missing-dependency'; shutil.copytree(asset_root, missing)
manifest = json.loads((missing / 'manifest.json').read_text(encoding='utf-8'))
manifest['tools'][0]['version'] = '==9.9.9'
(missing / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
for invalid in (missing,):
 try: run_litho_cpk_demo_sync('ready', package_root=str(invalid))
 except ValueError: pass
 else: raise AssertionError('missing dependency accepted')
bad = unit / 'invalid-manifest'; shutil.copytree(asset_root, bad)
(bad / 'manifest.json').write_text('{not-json', encoding='utf-8')
try: run_litho_cpk_demo_sync('ready', package_root=str(bad))
except ValueError: pass
else: raise AssertionError('invalid manifest accepted')
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
            # Windows requires its system roots while importing the Proactor
            # event-loop implementation.  The child replaces this minimal
            # bootstrap environment with DenyEnvironment before app imports.
            child_env = {
                key: value
                for key, value in os.environ.items()
                if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT"}
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    code,
                    str(unit),
                    str(copied_assets),
                    *SOURCE_FILES,
                ],
                cwd=Path(tempfile.gettempdir()),
                env=child_env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
