"""Released Cpk Skill runs from the exact MOD-018 source closure plus releases."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_litho_cpk_portable import SOURCE_FILES as MOD018_SOURCE_FILES

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (*MOD018_SOURCE_FILES, "app/skills/releases.py")
ASSETS = (
    "manifest.json",
    "SKILL.md",
    "references/cpk_context.md",
    "scenarios/acceptance.json",
)


class SkillReleasesPortableTests(unittest.TestCase):
    def test_released_ready_and_loop_use_only_the_explicit_96_file_slice(self) -> None:
        self.assertEqual(len(SOURCE_FILES), 96)
        with tempfile.TemporaryDirectory() as temporary:
            unit = Path(temporary) / "unit"
            for relative in SOURCE_FILES:
                destination = unit / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            release_root = unit / "author" / "v1"
            for relative in ASSETS:
                destination = release_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(
                    ROOT
                    / "app"
                    / "skills"
                    / "lithography"
                    / "cpk_diagnostic"
                    / relative,
                    destination,
                )
            code = r"""
import asyncio, importlib, importlib.abc, inspect, json, os, shutil, socket, sqlite3, subprocess, sys, time
from datetime import date
from pathlib import Path
unit, author = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
allowed = set(sys.argv[3:]); sys.path.insert(0, str(unit))
stdlib_asyncio = (Path(sys.base_prefix) / 'Lib' / 'asyncio').resolve()
warm = asyncio.new_event_loop(); warm.close()
blocked = ('app.agent_runtime.service', 'app.agent_runtime.compatibility',
 'app.agent_runtime.execution.agent_loop', 'app.agent_runtime.tools.catalog',
 'app.agent_runtime.tools.registry', 'app.core', 'app.model_gateway', 'app.persistence',
 'app.telemetry', 'app.conversation')
events = []
class BlockedFinder(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if any(fullname == item or fullname.startswith(item + '.') for item in blocked):
   events.append(('import', fullname)); raise AssertionError(fullname)
  return None
class DenyEnvironment(dict):
 def __getitem__(self, key):
  if key in {'PYTHONASYNCIODEBUG','LANG','LANGUAGE','COLUMNS','LINES','TERM'} or key.startswith('LC_'): return ''
  raise AssertionError('environment read: ' + key)
 def get(self, key, default=None): return self[key]
 def __iter__(self): raise AssertionError('environment iteration')
 def __contains__(self, key): raise AssertionError('environment contains')
 def keys(self): raise AssertionError('environment keys')
 def items(self): raise AssertionError('environment items')
 def values(self): raise AssertionError('environment values')
 def copy(self): raise AssertionError('environment copy')
 def update(self, *args, **kwargs): raise AssertionError('environment update')
 def __setitem__(self, key, value): raise AssertionError('environment write')
sys.meta_path.insert(0, BlockedFinder()); os.environ = DenyEnvironment()
os.getenv = lambda key, default=None: os.environ.get(key, default)
def audit(event, args):
 if event in {'sqlite3.connect','socket.connect','socket.getaddrinfo','socket.gethostbyname','subprocess.Popen','os.system'}:
  target = args[1] if len(args) > 1 else ()
  if (event == 'socket.connect' and os.name == 'nt' and isinstance(target, tuple)
      and target and target[0] == '127.0.0.1' and any(
       frame.function == '_make_self_pipe' and Path(frame.filename).resolve().is_relative_to(stdlib_asyncio)
       and frame.filename.replace('\\','/').endswith('/asyncio/proactor_events.py') for frame in inspect.stack())): return
  events.append((event,args)); raise AssertionError(event)
sys.addaudithook(audit)
for operation in (lambda: importlib.import_module('app.agent_runtime.service'),
 lambda: os.environ.get('FAB_DATABASE_PATH'), lambda: socket.socket().connect(('127.0.0.1',9)),
 lambda: socket.getaddrinfo('example.invalid',443), lambda: sqlite3.connect(':memory:'),
 lambda: subprocess.Popen(('python','-c','pass')), lambda: os.system('exit 0')):
 try: operation()
 except AssertionError: pass
 else: raise AssertionError('negative control')
assert {event for event,_ in events} >= {'import','socket.connect','socket.getaddrinfo','sqlite3.connect','subprocess.Popen','os.system'}
async def async_network_negative_control(): socket.socket().connect(('127.0.0.1',9))
try: asyncio.run(async_network_negative_control())
except AssertionError: pass
else: raise AssertionError('async socket control')
events.clear()
from app.agent_runtime.definition import AgentDefinition, ComponentReference
from app.agent_runtime.execution.loop_dispatch import execute_dispatched_loop_round
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.loop_response import classify_loop_response
from app.agent_runtime.execution.ready_dispatch import execute_dispatched_ready_plan
from app.agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from app.agent_runtime.execution.runtime_contracts import ModelMessage, ModelResponse, ModelToolCall, RuntimeContext
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import ToolExecutionLimits
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.bootstrap.agent_assembly import AssemblyError, assemble_agent
from app.bootstrap.litho_cpk_demo import _Principal, _QUESTION, _TOOLS, _bindings
from app.bootstrap.litho_cpk_workflow import LithoCpkWorkflow
from app.bootstrap.loop_assembly import bind_loop_run
from app.bootstrap.ready_assembly import bind_ready_run
from app.bootstrap.skill_assembly import SkillAssemblyConfiguration, SkillExecutionRequest, _inventory
from app.evidence.validator import EvidenceObservation
from app.intent_runtime.routing import route_question
from app.knowledge.decision import usable_result
from app.skills.catalog import SkillReference
from app.skills.releases import SkillReleaseStore
route = route_question(_QUESTION, date(2026,10,31)); workflow = LithoCpkWorkflow(); plan,_ = workflow.build(_QUESTION,route)
bindings, adapters = _bindings(plan,date(2026,10,31),_Principal()); inventory = _inventory(bindings,(workflow,))
store = SkillReleaseStore(); (author/'SKILL.md').write_text('# published one\n'); store.publish(author,inventory); v1 = SkillReference('litho-cpk-diagnostic','1.0.0'); store.activate(v1)
class Events:
 async def emit(self,event): return None
class Model:
 def __init__(self,plan): self.plan,self.calls,self.requests=plan,0,[]
 async def complete(self,request,context):
  self.calls+=1;self.requests.append(request)
  if request.call_id == 'first': return ModelResponse(tool_calls=tuple(ModelToolCall(str(i),step.tool,json.dumps(step.parameters)) for i,step in enumerate(self.plan.steps,1)))
  return ModelResponse(content='done')
def app_for(reference):
 definition=AgentDefinition('portable-release','1.0.0','analyst','released',tuple(ComponentReference(n,'1.0.0') for n in _TOOLS),ComponentReference('model','1.0.0'),ComponentReference('policy','1.0.0'),(ComponentReference(reference.skill_id,reference.version),))
 model=Model(plan); holder={}
 def budget():
  guard=ToolLoopGuard(app.skill_binding.plan); holder['guard']=guard; return LoopGuardToolBudget(guard)
 app=assemble_agent(definition,model=model,events=Events(),bindings=bindings,policy=DemoToolPolicy(frozenset(_TOOLS),frozenset({'analyst'}),tenant_id='demo'),budget_factory=budget,server_capabilities=frozenset(_TOOLS),model_policy_ref=definition.model_policy,policy_ref=definition.default_policy,skill_configuration=SkillAssemblyConfiguration((),(workflow,),store),skill_request=SkillExecutionRequest(_QUESTION,route,'loop'))
 return app,model,holder
async def execute(app,model,holder,mode,run=None):
 if run is None:
  context=RuntimeContext(_Principal(),'portable-'+mode,ToolExecutionLimits(20,100,time.monotonic()+5)); projector=ReadyResultPolicy(frozenset({'search_knowledge'}),usable_result); run=app.new_run(context,result_policy=projector); guard=holder['guard']
 else:
  context=run.context; projector=run.dispatcher.result_policy; guard=holder['guard']
 async def notify(progress,event): return None
 if mode == 'ready':
  binding=bind_ready_run(app.skill_binding.plan,guard,run,projector); outcome=await execute_dispatched_ready_plan(app.skill_binding.plan,guard,context.run_id,None,binding=binding,notify=notify,emit_event=lambda *a,**k:None)
 else:
  binding=bind_loop_run(app.skill_binding.plan,guard,run,projector); first=await run.model_stage(call_id='first',messages=(ModelMessage('user',_QUESTION),)); outcome=await execute_dispatched_loop_round(app.skill_binding.plan,guard,context.run_id,1,classify_loop_response(first.value),None,binding=binding,notify=notify,emit_event=lambda *a,**k:None); await run.model_stage(call_id='second',messages=(ModelMessage('user',_QUESTION),ModelMessage('assistant','',tool_calls=first.value.tool_calls),*(ModelMessage('tool',x['content'],tool_call_id=x['tool_call_id']) for x in outcome.tool_messages)))
 observations=tuple(EvidenceObservation(**item) for item in outcome.observation_payloads); validation=app.skill_binding.workflow.evidence_validator(app.skill_binding.plan,app.skill_binding.selection.selected_playbook,list(observations)); assert validation.coverage['required_covered']==3; assert all(x['status']=='ok' for x in outcome.trace); return run
old,oldmodel,oldholder=app_for(v1); oldprojector=ReadyResultPolicy(frozenset({'search_knowledge'}),usable_result); oldrun=old.new_run(RuntimeContext(_Principal(),'portable-old',ToolExecutionLimits(20,100,time.monotonic()+5)),result_policy=oldprojector)
v2root = author.parent / 'v2'; shutil.copytree(author,v2root); manifest=json.loads((v2root/'manifest.json').read_text()); manifest['version']='2.0.0'; (v2root/'manifest.json').write_text(json.dumps(manifest)); (v2root/'SKILL.md').write_text('# published two\n'); store.publish(v2root,inventory); shutil.rmtree(author)
asyncio.run(oldrun.model_stage(call_id='old-after-publication',messages=(ModelMessage('user',_QUESTION),))); assert 'published one' in oldmodel.requests[-1].messages[1].content
oldrun=asyncio.run(execute(old,oldmodel,oldholder,'ready',oldrun)); store.activate(SkillReference('litho-cpk-diagnostic','2.0.0')); new,newmodel,newholder=app_for(SkillReference('litho-cpk-diagnostic','2.0.0')); newrun=asyncio.run(execute(new,newmodel,newholder,'loop'))
assert old.skill_binding.snapshot.reference == v1 and new.skill_binding.snapshot.reference.version == '2.0.0'
store.disable(SkillReference('litho-cpk-diagnostic','2.0.0'))
try: new.new_run(RuntimeContext(_Principal(),'disabled',ToolExecutionLimits()))
except AssemblyError: pass
else: raise AssertionError('disabled new run accepted')
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
assert DEFAULT_TOOL_REGISTRY.model_tools == [] and DEFAULT_TOOL_REGISTRY.legacy_handlers == {}
for name,module in list(sys.modules.items()):
 if name == 'app' or name.startswith('app.'):
  origin=Path(module.__file__).resolve(); assert origin.is_relative_to(unit),origin; assert origin.relative_to(unit).as_posix() in allowed,origin
assert not events and not any(name == item or name.startswith(item+'.') for name in sys.modules for item in blocked)
"""
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
                    str(release_root),
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
