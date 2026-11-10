"""Portable, source-closed acceptance for the explicit MOD-009 tool sources."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# This is the imported closure of the real fake-source Ready/Loop demonstration.
# It deliberately copies individual files, including package anchors, not an app tree
# and not replacement stubs.
SOURCE_FILES = (
    "app/__init__.py",
    "app/agent_runtime/__init__.py",
    "app/agent_runtime/application.py",
    "app/agent_runtime/contracts.py",
    "app/agent_runtime/coordinator.py",
    "app/agent_runtime/coordinator_state.py",
    "app/agent_runtime/definition.py",
    "app/agent_runtime/dependencies.py",
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
    "app/agent_runtime/stages/__init__.py",
    "app/agent_runtime/stages/availability.py",
    "app/agent_runtime/stages/loop.py",
    "app/agent_runtime/stages/model.py",
    "app/agent_runtime/stages/prepare.py",
    "app/agent_runtime/stages/ready.py",
    "app/agent_runtime/tools/__init__.py",
    "app/agent_runtime/tools/contracts.py",
    "app/agent_runtime/tools/definition.py",
    "app/agent_runtime/tools/dispatch_contracts.py",
    "app/agent_runtime/tools/dispatch_policy.py",
    "app/agent_runtime/tools/dispatcher.py",
    "app/agent_runtime/tools/projection.py",
    "app/agent_runtime/tools/tool_registry.py",
    "app/bootstrap/__init__.py",
    "app/bootstrap/agent_assembly.py",
    "app/bootstrap/diagnostics_demo.py",
    "app/bootstrap/enterprise_tools_demo.py",
    "app/bootstrap/knowledge_search_demo.py",
    "app/bootstrap/loop_assembly.py",
    "app/bootstrap/named_queries_demo.py",
    "app/bootstrap/operational_reports_demo.py",
    "app/bootstrap/production_reports_demo.py",
    "app/bootstrap/ready_assembly.py",
    "app/bootstrap/tool_sources.py",
    "app/bootstrap/tool_sources_demo.py",
    "app/core/__init__.py",
    "app/core/sqlite_support.py",
    "app/core/tool_result_projection.py",
    "app/integrations/__init__.py",
    "app/integrations/knowledge/__init__.py",
    "app/integrations/knowledge/backend_search.py",
    "app/integrations/knowledge/fake_search.py",
    "app/integrations/manufacturing/__init__.py",
    "app/demo_data/tool_sources/enterprise_data.py",
    "app/demo_data/tool_sources/equipment_health.py",
    "app/demo_data/tool_sources/named_queries.py",
    "app/demo_data/tool_sources/operational_reports.py",
    "app/demo_data/tool_sources/process_diagnostics.py",
    "app/demo_data/tool_sources/production_reports.py",
    "app/tools/enterprise_data/data_source.py",
    "app/tools/equipment_health/data_source.py",
    "app/tools/named_queries/data_source.py",
    "app/tools/operational_reports/data_source.py",
    "app/tools/process_diagnostics/data_source.py",
    "app/tools/production_reports/data_source.py",
    "app/knowledge/__init__.py",
    "app/knowledge/ranking.py",
    "app/knowledge/search_contracts.py",
    "app/knowledge/search_policy.py",
    "app/knowledge/search_query.py",
    "app/knowledge/search_tool/__init__.py",
    "app/knowledge/search_tool/binding.py",
    "app/knowledge/search_tool/contracts.py",
    "app/knowledge/search_tool/handler.py",
    "app/manufacturing/__init__.py",
    "app/tools/enterprise_data/provider_contracts.py",
    "app/tools/enterprise_data/__init__.py",
    "app/tools/enterprise_data/binding.py",
    "app/tools/enterprise_data/contracts.py",
    "app/tools/enterprise_data/handler.py",
    "app/tools/equipment_health/__init__.py",
    "app/tools/equipment_health/binding.py",
    "app/tools/equipment_health/contracts.py",
    "app/tools/equipment_health/handler.py",
    "app/tools/equipment_health/summary.py",
    "app/tools/named_queries/__init__.py",
    "app/tools/named_queries/binding.py",
    "app/tools/named_queries/contracts.py",
    "app/tools/named_queries/handler.py",
    "app/tools/operational_reports/__init__.py",
    "app/tools/operational_reports/binding.py",
    "app/tools/operational_reports/contracts.py",
    "app/tools/operational_reports/handler.py",
    "app/tools/process_diagnostics/__init__.py",
    "app/tools/process_diagnostics/binding.py",
    "app/tools/process_diagnostics/contracts.py",
    "app/tools/process_diagnostics/handler.py",
    "app/manufacturing/processes.py",
    "app/tools/production_reports/__init__.py",
    "app/tools/production_reports/binding.py",
    "app/tools/production_reports/contracts.py",
    "app/tools/production_reports/handler.py",
    "app/planning_runtime/__init__.py",
    "app/planning_runtime/contracts.py",
    "app/demo_data/__init__.py",
    "app/demo_data/tool_sources/__init__.py",
    "app/tools/__init__.py",
)


class ToolSourcesPortableTests(unittest.TestCase):
    def test_fake_sources_run_all_ready_loop_cases_from_the_declared_slice(
        self,
    ) -> None:
        self.assertEqual(len(SOURCE_FILES), len(set(SOURCE_FILES)))
        evaluation = json.loads(
            (ROOT / "evaluations" / "mod_009_tool_sources_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(evaluation["portable_source_files"], list(SOURCE_FILES))
        with tempfile.TemporaryDirectory() as raw:
            unit = Path(raw) / "unit"
            for relative in SOURCE_FILES:
                source, destination = ROOT / relative, unit / relative
                self.assertTrue(source.is_file(), relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            code = r"""
import argparse, asyncio, importlib, importlib.abc, inspect, json, os, socket, sqlite3, subprocess, sys, tempfile
from pathlib import Path
unit=Path(sys.argv[1]).resolve(); original=Path(sys.argv[2]).resolve(); allowed=set(sys.argv[3:]); assert not any(Path(value).resolve()==original for value in sys.path if value); sys.path.insert(0,str(unit))
stdlib_asyncio=(Path(sys.base_prefix)/'Lib'/'asyncio').resolve()
argparse.ArgumentParser(); tempfile.gettempdir(); warm=asyncio.new_event_loop(); warm.close()
blocked=('app.core.settings','app.core.identity','app.core.identity_contracts','app.persistence','app.agent_runtime.service','app.agent_runtime.compatibility','app.agent_runtime.tools.catalog','app.agent_runtime.tools.registry','app.model_gateway','app.knowledge.rag','app.manufacturing.reports','app.bootstrap.default_tool_assembly','app.bootstrap.default_coordinator_assembly','app.bootstrap.tool_catalog','app.bootstrap.tool_bindings','app.main')
events=[]
class Finder(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if any(fullname==item or fullname.startswith(item+'.') for item in blocked): events.append(('import',fullname)); raise AssertionError(fullname)
  return None
class Env(dict):
 def __getitem__(self,key):
  if key in {'PYTHONASYNCIODEBUG','LANG','LANGUAGE','COLUMNS','LINES','TERM'} or key.startswith('LC_'): return ''
  events.append(('env',key)); raise AssertionError('environment read')
 def get(self,key,default=None): return self[key]
 def __iter__(self): events.append(('env','iter')); raise AssertionError('environment iteration')
 def __contains__(self,key): events.append(('env','contains')); raise AssertionError('environment contains')
 def keys(self): events.append(('env','keys')); raise AssertionError('environment keys')
 def items(self): events.append(('env','items')); raise AssertionError('environment items')
 def values(self): events.append(('env','values')); raise AssertionError('environment values')
 def copy(self): events.append(('env','copy')); raise AssertionError('environment copy')
sys.meta_path.insert(0,Finder()); os.environ=Env(); os.getenv=lambda key,default=None: os.environ.get(key,default)
def audit(event,args):
 if event in {'sqlite3.connect','socket.connect','socket.getaddrinfo','socket.gethostbyname','subprocess.Popen','os.system'}:
  target=args[1] if len(args)>1 else ()
  if event=='socket.connect' and os.name=='nt' and isinstance(target,tuple) and target and target[0]=='127.0.0.1' and any(frame.function=='_make_self_pipe' and Path(frame.filename).resolve().is_relative_to(stdlib_asyncio) and frame.filename.replace('\\','/').endswith('/asyncio/proactor_events.py') for frame in inspect.stack()): return
  events.append((event,args)); raise AssertionError(event)
sys.addaudithook(audit)
for operation in (lambda:importlib.import_module('app.persistence'), lambda:os.environ.get('FAB_DATABASE_PATH'), lambda:iter(os.environ), lambda:('FAB_DATABASE_PATH' in os.environ), lambda:os.environ.keys(), lambda:os.environ.items(), lambda:os.environ.values(), lambda:os.environ.copy(), lambda:socket.socket().connect(('127.0.0.1',9)), lambda:socket.getaddrinfo('example.invalid',443), lambda:socket.gethostbyname('example.invalid'), lambda:sqlite3.connect(':memory:'), lambda:subprocess.Popen(('python','-c','pass')), lambda:os.system('exit 0')):
 try: operation()
 except AssertionError: pass
 else: raise AssertionError('negative control')
assert {x[0] for x in events}>={'import','env','socket.connect','socket.getaddrinfo','socket.gethostbyname','sqlite3.connect','subprocess.Popen','os.system'},events
events.clear()
from app.bootstrap.tool_sources_demo import AS_OF, build_fake_sources, run_tool_sources
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
names=('get_equipment_health','get_process_capability','get_sensor_summary','get_fab_overview','get_yield_trend','get_process_pass_rate','get_equipment_productivity','get_defect_pareto','get_recent_excursions','get_enterprise_data_manifest','get_enterprise_fab_summary','query_enterprise_data','search_knowledge','get_product_yield_breakdown','get_equipment_event_timeline','get_equipment_excursion_history','get_lot_identity','get_lot_process_history','get_lot_excursion_history','get_lot_defect_history','get_lot_wafer_map_patterns')
async def main():
 sources=build_fake_sources(AS_OF); cases=0
 for tool in names+('get_equipment_health_summary',):
  for mode in ('ready','loop'):
   is_equipment_summary=tool=='get_equipment_health_summary'
   result=await run_tool_sources(sources,tool=tool,mode=mode,as_of=AS_OF,include_summary=is_equipment_summary)
   assert result['status']=='succeeded',(tool,mode,result)
   assert result['guard_total_calls']==1,(tool,mode,result)
   assert result['model_calls']==(0 if mode=='ready' else 2),(tool,mode,result)
   assert result['model_tool_count']==(22 if is_equipment_summary else 21),(tool,mode,result)
   assert result['sources'],(tool,mode,result)
   assert all(item['kind']=='fake' for item in result['sources']),(tool,mode,result)
   cases+=1
 return cases
cases=asyncio.run(main()); assert cases==44
assert not events,events
assert DEFAULT_TOOL_REGISTRY.model_tools==[] and DEFAULT_TOOL_REGISTRY.legacy_handlers=={}
for name,module in list(sys.modules.items()):
 if name=='app' or name.startswith('app.'):
  origin=Path(module.__file__).resolve(); assert origin.is_relative_to(unit),origin; assert origin.relative_to(unit).as_posix() in allowed,origin
print(json.dumps({'cases':cases,'file_count':len(allowed),'guard_events':len(events),'sqlite_calls':0,'network_calls':0}))
"""
            child_env = (
                {}
                if os.name != "nt"
                else {
                    key: value
                    for key, value in os.environ.items()
                    if key.upper()
                    in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT"}
                }
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    code,
                    str(unit),
                    str(ROOT),
                    *SOURCE_FILES,
                ],
                cwd=tempfile.gettempdir(),
                env=child_env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload,
                {
                    "cases": 44,
                    "file_count": len(SOURCE_FILES),
                    "guard_events": 0,
                    "sqlite_calls": 0,
                    "network_calls": 0,
                },
            )
