"""Execute the enterprise demo from its explicit isolated source slice."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import scrubbed_environment
from tests.test_operational_reports_portable import OPERATIONAL_FILES
from tests.test_process_diagnostics_portable import (
    DIAGNOSTICS_FILES,
    INVENTORY,
    LOOP_FILES,
    MODERN_FILES,
    READY_FILES,
    ROOT,
    RUNTIME_FILES,
)
from tests.test_production_reports_portable import PRODUCTION_FILES

ENTERPRISE_FILES = (
    "app/manufacturing/data_contracts.py",
    "app/manufacturing/enterprise_tools/__init__.py",
    "app/manufacturing/enterprise_tools/contracts.py",
    "app/manufacturing/enterprise_tools/handler.py",
    "app/manufacturing/enterprise_tools/binding.py",
    "app/integrations/manufacturing/fake_enterprise_tools.py",
    "app/integrations/manufacturing/provider_enterprise_tools.py",
    "app/bootstrap/enterprise_tools_demo.py",
)


class EnterpriseToolsPortableTests(unittest.TestCase):
    def test_real_84_file_slice_cannot_reach_repository_or_system_resources(
        self,
    ) -> None:
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
            + OPERATIONAL_FILES
            + ENTERPRISE_FILES
        )
        self.assertEqual((len(files), len(set(files))), (88, 88))
        with tempfile.TemporaryDirectory() as raw:
            unit = Path(raw) / "unit"
            for relative in files:
                source, target = ROOT / relative, unit / relative
                self.assertTrue(source.is_file(), relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            code = r"""import asyncio, importlib, importlib.abc, json, os, socket, sqlite3, sys
from pathlib import Path
unit=Path(sys.argv[1]).resolve(); original=Path(sys.argv[2]).resolve(); allowed=set(sys.argv[3:])
assert not any(str(unit) in value for value in sys.path)
assert not any(Path(value).resolve()==original for value in sys.path if value)
sys.path.insert(0,str(unit)); events=[]
# Create the Windows event loop before the audit hook; its loopback
# socketpair is local IPC, not application network access.
_loop=asyncio.new_event_loop(); asyncio.set_event_loop(_loop); asyncio.run=_loop.run_until_complete
blocked=('app.agent_runtime.service','app.agent_runtime.compatibility','app.agent_runtime.execution.agent_loop','app.agent_runtime.execution.loop_answer','app.agent_runtime.execution.loop_model_call','app.agent_runtime.execution.loop_request','app.agent_runtime.execution.loop_round_validation','app.agent_runtime.execution.loop_state','app.agent_runtime.execution.loop_tool_round','app.agent_runtime.tools.catalog','app.agent_runtime.tools.registry','app.core.settings','app.core.identity','app.model_gateway','app.evidence','app.persistence','app.manufacturing.enterprise_data','app.manufacturing.reports')
class Finder(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==item or fullname.startswith(item+'.') for item in blocked): events.append(('import',fullname));raise AssertionError(fullname)
  return None
class Env(dict):
 def __getitem__(self,key):
  if key in {'LANG','LANGUAGE','COLUMNS','LINES','TERM'} or key.startswith('LC_'): return ''
  raise AssertionError('env:'+key)
 def get(self,key,default=None):
  if key in {'LANG','LANGUAGE','COLUMNS','LINES','TERM'} or key.startswith('LC_'): return ''
  raise AssertionError('env:'+key)
 def __iter__(self): raise AssertionError('environment iteration')
 def keys(self): raise AssertionError('environment keys')
 def items(self): raise AssertionError('environment items')
 def values(self): raise AssertionError('environment values')
 def copy(self): raise AssertionError('environment copy')
 def __contains__(self,key): raise AssertionError('environment contains')
sys.meta_path.insert(0,Finder()); os.environ=Env(); os.getenv=lambda key,default=None:os.environ.get(key,default)
def audit(event,args):
 if event in {'sqlite3.connect','socket.connect','socket.getaddrinfo','socket.gethostbyname'}: events.append((event,args));raise AssertionError(event)
sys.addaudithook(audit)
for op in (lambda:importlib.import_module('app.agent_runtime.service'),lambda:os.environ.get('FAB_DATABASE_PATH'),lambda:iter(os.environ),lambda:os.environ.keys(),lambda:os.environ.items(),lambda:os.environ.values(),lambda:os.environ.copy(),lambda:('FAB_DATABASE_PATH' in os.environ),lambda:socket.socket().connect(('127.0.0.1',9)),lambda:socket.getaddrinfo('example.invalid',443),lambda:sqlite3.connect(':memory:')):
 try:op()
 except AssertionError:pass
 else:raise AssertionError('negative guard control failed')
assert any(event=='import' for event,_ in events)
assert any(event=='socket.connect' for event,_ in events)
assert any(event=='socket.getaddrinfo' for event,_ in events)
assert any(event=='sqlite3.connect' for event,_ in events)
events.clear()
from app.bootstrap import enterprise_tools_demo as d
out=[];d.print=lambda *x,**k:out.append(x[0])
for tool,args,grain in (('get_enterprise_data_manifest','{}','enterprise_manifest'),('get_enterprise_fab_summary','{}','enterprise_aggregate'),('query_enterprise_data','{"entity":"lots"}','enterprise_sample')):
 for mode in ('ready','loop'):
  assert d.main(['--mode',mode,'--adapter','fake','--tool',tool,'--arguments',args])==0,(tool,mode,out[-1] if out else None)
  payload=json.loads(out[-1]);assert payload['typed_results'][0]['status']=='succeeded';assert next(iter(payload['sources'].values()))['scope']['grain']==grain
assert d.main(['--adapter','provider','--tool','query_enterprise_data','--arguments','{"entity":"sensor-events","process_step":"CMP","equipment_id":"CMP-01","signal_name":"RF power"}'])==0
assert not events
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
assert DEFAULT_TOOL_REGISTRY.model_tools==[] and DEFAULT_TOOL_REGISTRY.legacy_handlers=={}
for name,module in list(sys.modules.items()):
 if name=='app' or name.startswith('app.'):
  origin=Path(module.__file__).resolve();assert origin.is_relative_to(unit),origin;assert origin.relative_to(unit).as_posix() in allowed,origin
"""
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-c", code, str(unit), str(ROOT), *files],
                cwd=Path(tempfile.gettempdir()),
                env=scrubbed_environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
