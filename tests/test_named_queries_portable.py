"""Exercise the declared source slice with persistent resource and import guards."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import scrubbed_environment
from tests.test_loop_dispatcher_portable import (
    INVENTORY,
    LOOP_FILES,
    MODERN_FILES,
    READY_FILES,
    ROOT,
    RUNTIME_FILES,
)

FILES = (
    "app/manufacturing/named_queries/__init__.py",
    "app/manufacturing/named_queries/contracts.py",
    "app/manufacturing/named_queries/handler.py",
    "app/manufacturing/named_queries/binding.py",
    "app/integrations/manufacturing/fake_named_queries.py",
    "app/integrations/manufacturing/sqlite_named_queries.py",
    "app/bootstrap/named_queries_demo.py",
)


class NamedQueriesPortableTests(unittest.TestCase):
    def test_all_sixteen_paths_run_from_guarded_real_62_file_slice(self) -> None:
        base = json.loads(INVENTORY.read_text(encoding="utf-8"))["units"][
            "dispatcher_pilot"
        ]["files"]
        files = (
            tuple(base)
            + RUNTIME_FILES
            + MODERN_FILES
            + READY_FILES
            + LOOP_FILES
            + FILES
        )
        self.assertEqual((len(files), len(set(files))), (66, 66))
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
assert not any(Path(value).resolve()==original for value in sys.path if value)
sys.path.insert(0,str(unit)); events=[]
# Create the Windows event loop before the audit hook; its loopback
# socketpair is local IPC, not application network access.
_loop=asyncio.new_event_loop(); asyncio.set_event_loop(_loop); asyncio.run=_loop.run_until_complete
blocked=('app.agent_runtime.service','app.agent_runtime.compatibility','app.agent_runtime.execution.agent_loop','app.agent_runtime.execution.loop_answer','app.agent_runtime.execution.loop_model_call','app.agent_runtime.execution.loop_request','app.agent_runtime.execution.loop_round_validation','app.agent_runtime.execution.loop_state','app.agent_runtime.execution.loop_tool_round','app.agent_runtime.tools.catalog','app.agent_runtime.tools.registry','app.core.settings','app.core.identity','app.persistence','app.model_gateway','app.evidence','app.manufacturing.reports','app.planning_runtime.queries')
class Finder(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if any(fullname==item or fullname.startswith(item+'.') for item in blocked):events.append(('import',fullname));raise AssertionError(fullname)
  return None
def deny(label):events.append(('env',label));raise AssertionError(label)
class Env(dict):
 def __getitem__(self,key):
  if key in {'LANG','LANGUAGE','COLUMNS','LINES','TERM'} or key.startswith('LC_'):return ''
  return deny('env:'+key)
 def get(self,key,default=None):return self[key]
 def __iter__(self):return deny('iteration')
 def keys(self):return deny('keys')
 def items(self):return deny('items')
 def values(self):return deny('values')
 def copy(self):return deny('copy')
 def __contains__(self,key):return deny('contains')
sys.meta_path.insert(0,Finder());os.environ=Env();os.getenv=lambda key,default=None:os.environ.get(key,default)
def audit(event,args):
 if event in {'sqlite3.connect','socket.connect','socket.getaddrinfo','socket.gethostbyname'}:events.append((event,args));raise AssertionError(event)
sys.addaudithook(audit)
for op in (lambda:importlib.import_module('app.manufacturing.reports'),lambda:os.environ.get('FAB_DATABASE_PATH'),lambda:iter(os.environ),lambda:os.environ.keys(),lambda:os.environ.items(),lambda:os.environ.values(),lambda:os.environ.copy(),lambda:('X' in os.environ),lambda:socket.socket().connect(('127.0.0.1',9)),lambda:socket.getaddrinfo('example.invalid',443),lambda:sqlite3.connect(':memory:')):
 try:op()
 except AssertionError:pass
 else:raise AssertionError('negative guard control failed')
for category in ('import','env','socket.connect','socket.getaddrinfo','sqlite3.connect'):assert any(name==category for name,_ in events),category
events.clear()
from app.bootstrap import named_queries_demo as demo
out=[];demo.print=lambda *a,**k:out.append(a[0])
cases=(('get_product_yield_breakdown','{}'),('get_equipment_event_timeline','{}'),('get_equipment_excursion_history','{}'),('get_lot_identity','{"lot_id":"L1"}'),('get_lot_process_history','{"lot_id":"L1"}'),('get_lot_excursion_history','{"lot_id":"L1"}'),('get_lot_defect_history','{"lot_id":"L1"}'),('get_lot_wafer_map_patterns','{"lot_id":"L1"}'))
for tool,args in cases:
 for mode in ('ready','loop'):
  assert demo.main(['--tool',tool,'--arguments',args,'--mode',mode])==0,(tool,mode,out[-1] if out else None)
  payload=json.loads(out[-1]);assert payload['typed_results'][0]['status']=='succeeded';assert payload['model_response_calls']==(0 if mode=='ready' else 2)
assert not events,events
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
assert DEFAULT_TOOL_REGISTRY.model_tools==[] and DEFAULT_TOOL_REGISTRY.legacy_handlers=={}
for name,module in list(sys.modules.items()):
 if name=='app' or name.startswith('app.'):
  origin=Path(module.__file__).resolve();assert origin.is_relative_to(unit),origin;assert origin.relative_to(unit).as_posix() in allowed,origin
"""
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-c", code, str(unit), str(ROOT), *files],
                cwd=tempfile.gettempdir(),
                env=scrubbed_environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
