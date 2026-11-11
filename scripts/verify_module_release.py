"""Actual, isolated acceptance checks for a MOD-024 delivery directory.

This tool deliberately invokes the installer bundled with ``--delivery``.  It
does not import an ``app`` module from this checkout; each workload runs in a
fresh virtual environment from an unrelated working directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import venv
from pathlib import Path
from typing import Any

TOOLS = (
    "get_equipment_health",
    "get_process_capability",
    "get_sensor_summary",
    "get_fab_overview",
    "get_yield_trend",
    "get_process_pass_rate",
    "get_equipment_productivity",
    "get_defect_pareto",
    "get_recent_excursions",
    "get_enterprise_data_manifest",
    "get_enterprise_fab_summary",
    "query_enterprise_data",
    "search_knowledge",
    "get_product_yield_breakdown",
    "get_equipment_event_timeline",
    "get_equipment_excursion_history",
    "get_lot_identity",
    "get_lot_process_history",
    "get_lot_excursion_history",
    "get_lot_defect_history",
    "get_lot_wafer_map_patterns",
)


def _child_env() -> dict[str, str]:
    """Keep Windows process bootstrap variables, but no business configuration."""
    if os.name != "nt":
        return {}
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _python(venv_root: Path) -> Path:
    return venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _purelib(python: Path) -> Path:
    text = subprocess.check_output(
        [
            str(python),
            "-I",
            "-X",
            "utf8",
            "-c",
            "import sysconfig;print(sysconfig.get_paths()['purelib'])",
        ],
        text=True,
        env=_child_env(),
    )
    return Path(text.strip())


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, env=_child_env(), text=True, capture_output=True, check=False
    )


def _make_venv(root: Path, *, with_pip: bool) -> Path:
    if root.exists():
        raise ValueError("acceptance requires a new work directory")
    venv.EnvBuilder(with_pip=with_pip).create(root)
    python = _python(root)
    if not python.is_file():
        raise RuntimeError(f"venv Python was not created: {python}")
    return python


def _install(
    delivery: Path,
    python: Path,
    profiles: list[str],
    cwd: Path,
    wheelhouse: Path | None = None,
) -> None:
    command = [
        str(python),
        "-I",
        "-X",
        "utf8",
        str(delivery / "install_module_release.py"),
        "--delivery",
        str(delivery),
        "--target-python",
        str(python),
        "--target-site-packages",
        str(_purelib(python)),
        "--profiles",
        *profiles,
    ]
    if wheelhouse is not None:
        command.extend(["--wheelhouse", str(wheelhouse)])
    result = _run(command, cwd=cwd)
    if result.returncode:
        raise RuntimeError("installer failed:\n" + result.stdout + result.stderr)


_COMMON_GUARDS = r"""
import importlib, importlib.abc, inspect, json, os, socket, sqlite3, subprocess, sys
from pathlib import Path
events=[]
blocked=('app.core.settings','app.core.identity','app.core.model_credentials','app.persistence',
         'app.agent_runtime.service','app.agent_runtime.compatibility','app.agent_runtime.tools.catalog',
         'app.agent_runtime.tools.registry','app.model_gateway','app.knowledge.rag','app.api.report_service',
         'app.bootstrap.default_tool_assembly','app.bootstrap.default_coordinator_assembly','app.main')
class Finder(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if any(fullname==item or fullname.startswith(item+'.') for item in blocked):
   events.append(('import',fullname)); raise AssertionError(fullname)
  return None
class EmptyBusinessEnvironment(dict):
 def __getitem__(self,key):
  if key in {'PYTHONASYNCIODEBUG','LANG','LANGUAGE','COLUMNS','LINES','TERM'} or key.startswith('LC_'): return ''
  events.append(('env',key)); raise AssertionError('business environment read')
 def get(self,key,default=None): return self[key]
 def __iter__(self): events.append(('env','iter')); raise AssertionError('environment iteration')
 def __contains__(self,key): events.append(('env','contains')); raise AssertionError('environment contains')
 def keys(self): events.append(('env','keys')); raise AssertionError('environment keys')
 def items(self): events.append(('env','items')); raise AssertionError('environment items')
 def values(self): events.append(('env','values')); raise AssertionError('environment values')
 def copy(self): events.append(('env','copy')); raise AssertionError('environment copy')
sys.meta_path.insert(0,Finder()); os.environ=EmptyBusinessEnvironment(); os.getenv=lambda key,default=None: os.environ.get(key,default)
stdlib_asyncio=(Path(sys.base_prefix)/'Lib'/'asyncio').resolve()
def audit(event,args):
 if event in {'sqlite3.connect','socket.connect','socket.getaddrinfo','socket.gethostbyname','subprocess.Popen','os.system'}:
  target=args[1] if len(args)>1 else ()
  if event=='socket.connect' and os.name=='nt' and isinstance(target,tuple) and target and target[0]=='127.0.0.1' and any(frame.function=='_make_self_pipe' and Path(frame.filename).resolve().is_relative_to(stdlib_asyncio) and frame.filename.replace('\\','/').endswith('/asyncio/proactor_events.py') for frame in inspect.stack()): return
  events.append((event,args)); raise AssertionError(event)
sys.addaudithook(audit)
for op in (lambda:importlib.import_module('app.persistence'),lambda:os.environ.get('FAB_DATABASE_PATH'),lambda:iter(os.environ),lambda:socket.socket().connect(('127.0.0.1',9)),lambda:socket.getaddrinfo('example.invalid',443),lambda:socket.gethostbyname('example.invalid'),lambda:sqlite3.connect(':memory:'),lambda:subprocess.Popen(('python','-c','pass')),lambda:os.system('exit 0')):
 try: op()
 except AssertionError: pass
 else: raise AssertionError('negative control was accepted')
required={'import','env','socket.connect','socket.getaddrinfo','socket.gethostbyname','sqlite3.connect','subprocess.Popen','os.system'}
assert required <= {item[0] for item in events},events
events.clear()
"""


def _source_child_code(manifest: Path) -> str:
    names = repr(TOOLS)
    return (
        _COMMON_GUARDS
        + rf"""
import asyncio
manifest=json.loads(Path({str(manifest)!r}).read_text(encoding='utf-8'))
allowed=set(manifest['profiles']['tool_sources']['source_files']) | set(manifest['profiles']['skill_release']['source_files'])
allowed.update(path for path in manifest['ownership'] if path.startswith('app/skills/litho-cpk-diagnostic/'))
from app.bootstrap.tool_sources_demo import AS_OF, build_fake_sources, run_tool_sources
from app.bootstrap.litho_cpk_demo import run_litho_cpk_demo_sync
from app.agent_runtime.tools.tool_registry import DEFAULT_TOOL_REGISTRY
async def tools():
 sources=build_fake_sources(AS_OF); count=0
 for tool in {names} + ('get_equipment_health_summary',):
  for mode in ('ready','loop'):
   result=await run_tool_sources(sources,tool=tool,mode=mode,as_of=AS_OF,include_summary=(tool=='get_equipment_health_summary'))
   assert result['status']=='succeeded',(tool,mode,result)
   assert result['guard_total_calls']==1,(tool,mode,result)
   assert result['model_calls']==(0 if mode=='ready' else 2),(tool,mode,result)
   assert result['model_tool_count']==(22 if tool=='get_equipment_health_summary' else 21),(tool,mode,result)
   count+=1
 return count
cases=asyncio.run(tools()); assert cases==44
ready=run_litho_cpk_demo_sync('ready'); loop=run_litho_cpk_demo_sync('loop')
assert ready['validation'].coverage['required_covered']==3
assert loop['validation'].coverage['required_covered']==3
from app.skills.releases import SkillReleaseStore
from app.skills.catalog import SkillReference
from app.bootstrap.litho_cpk_demo import _Events, _Principal, _QUESTION, _ReadyModel, _TOOLS, _bindings
from app.bootstrap.litho_cpk_workflow import LithoCpkWorkflow
from app.bootstrap.skill_assembly import SkillAssemblyConfiguration, SkillExecutionRequest, _inventory
from app.bootstrap.agent_assembly import AssemblyError, assemble_agent
from app.agent_runtime.definition import AgentDefinition, ComponentReference
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.runtime_contracts import RuntimeContext
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.tools.contracts import ToolExecutionLimits
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.intent_runtime.routing import route_question
from datetime import date
import time
as_of=date(2026,10,31); workflow=LithoCpkWorkflow(); route=route_question(_QUESTION,as_of); plan,_=workflow.build(_QUESTION, route); bindings,_=_bindings(plan,as_of,_Principal())
store=SkillReleaseStore(); root=Path(__import__('app.bootstrap.litho_cpk_demo',fromlist=['x']).__file__).resolve().parents[1]/'skills'/'litho-cpk-diagnostic'
published=store.publish(root,_inventory(bindings,(workflow,))); ref=SkillReference('litho-cpk-diagnostic','2.0.0'); store.activate(ref)
before=published.resource('SKILL.md').text; (root/'SKILL.md').read_text(encoding='utf-8'); assert store.get(ref).resource('SKILL.md').text==before
definition=AgentDefinition('release-boundary','1.0.0','analyst','released',tuple(ComponentReference(item,'1.0.0') for item in _TOOLS),ComponentReference('model','1.0.0'),ComponentReference('policy','1.0.0'),(ComponentReference(ref.skill_id,ref.version),))
application=assemble_agent(definition,model=_ReadyModel(),events=_Events(),bindings=bindings,policy=DemoToolPolicy(frozenset(_TOOLS),frozenset({{'analyst'}}),tenant_id='demo'),budget_factory=lambda:LoopGuardToolBudget(ToolLoopGuard(plan)),server_capabilities=frozenset(_TOOLS),model_policy_ref=definition.model_policy,policy_ref=definition.default_policy,skill_configuration=SkillAssemblyConfiguration((),(workflow,),store),skill_request=SkillExecutionRequest(_QUESTION,route,'ready'))
store.disable(ref)
try: store.require_enabled(ref)
except Exception: pass
else: raise AssertionError('disabled release accepted for new run')
try: application.new_run(RuntimeContext(_Principal(),'disabled-new-run',ToolExecutionLimits(20,100,time.monotonic()+5)))
except AssemblyError: pass
else: raise AssertionError('disabled release accepted a new application run')
assert DEFAULT_TOOL_REGISTRY.model_tools==[] and DEFAULT_TOOL_REGISTRY.legacy_handlers=={{}}
for name,module in tuple(sys.modules.items()):
 if name=='app' or name.startswith('app.'):
  origin=Path(module.__file__).resolve(); purelib=Path(__import__('app').__file__).resolve().parents[1]
  assert origin.is_relative_to(purelib),origin
  assert origin.relative_to(purelib).as_posix() in allowed,origin
assert not events,events
print(json.dumps({{'tool_cases':cases,'cpk_modes':2,'release_disabled':True,'guard_events':0}},sort_keys=True))
"""
    )


_MODEL_CHILD = (
    _COMMON_GUARDS.replace("'app.model_gateway',", "")
    + r"""
import asyncio, json, socket
import httpx
from app.model_gateway.gateway import HttpModelGateway, ModelEndpoint
from app.model_gateway.streaming import stream_completion
def body(*events): return ''.join('data: '+event+'\n\n' for event in events).encode()
requests=[]
def handler(request):
 requests.append(request)
 return httpx.Response(200,content=body('{"choices":[{"delta":{"content":"ok"}}]}','{"usage":{"total_tokens":2}}','[DONE]'))
async def notify(*args): return None
async def protocol(client,url,headers,payload,progress,state=None): return await stream_completion(client,url,headers,payload,progress,state,notify=notify,disclosure_checker=lambda value: True)
def factory(**kwargs): return httpx.AsyncClient(transport=httpx.MockTransport(handler),trust_env=False,**kwargs)
async def main():
 gateway=HttpModelGateway(client_factory=factory,stream_completion=protocol)
 endpoint=ModelEndpoint('offline','offline','https://provider.invalid/v1','offline-key','merge-system')
 async with gateway.open(endpoint,timeout_seconds=3) as session:
  assistant,usage,_=await session.stream({'model':'offline','messages':[{'role':'user','content':'q'}]},None,{})
 assert assistant['content']=='ok' and usage=={'total_tokens':2}
 assert requests and requests[0].url==httpx.URL('https://provider.invalid/v1/chat/completions')
asyncio.run(main())
purelib=Path(__import__('app').__file__).resolve().parents[1]
for name,module in tuple(sys.modules.items()):
 if name=='app' or name.startswith('app.'):
  assert Path(module.__file__).resolve().is_relative_to(purelib),name
assert not events,events
print(json.dumps({'mock_transport':True,'network_calls':0},sort_keys=True))
"""
)


def verify(delivery: Path, work_dir: Path, wheelhouse: Path | None) -> dict[str, Any]:
    delivery = delivery.resolve()
    work_dir = work_dir.resolve()
    if work_dir.is_relative_to(delivery):
        raise ValueError("acceptance work directory must be outside delivery")
    if not (delivery / "install_module_release.py").is_file():
        raise ValueError("delivery does not contain its standalone installer")
    work_dir.mkdir(parents=True, exist_ok=True)
    copied = work_dir / "delivery-only"
    if copied.exists():
        raise ValueError("acceptance requires a new work directory")
    shutil.copytree(delivery, copied)
    cwd = work_dir / "unrelated-cwd"
    cwd.mkdir(exist_ok=True)
    report: dict[str, Any] = {"delivery": str(delivery), "profiles": {}}
    source_venv = work_dir / "source-venv"
    source_python = _make_venv(source_venv, with_pip=False)
    try:
        _install(copied, source_python, ["tool_sources", "skill_release"], cwd)
        result = _run(
            [
                str(source_python),
                "-I",
                "-X",
                "utf8",
                "-c",
                _source_child_code(copied / "module-release.json"),
            ],
            cwd=cwd,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        report["profiles"]["tool_sources+skill_release"] = {
            "status": "PASS",
            "result": json.loads(result.stdout),
        }
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        report["profiles"]["tool_sources+skill_release"] = {
            "status": "FAIL",
            "error": str(exc),
        }
    if wheelhouse is None:
        report["profiles"]["model_transport"] = {
            "status": "NOTRUN",
            "reason": "--wheelhouse was not supplied",
        }
    else:
        model_venv = work_dir / "model-venv"
        try:
            model_python = _make_venv(model_venv, with_pip=True)
            _install(
                copied,
                model_python,
                ["tool_sources", "skill_release", "model_transport"],
                cwd,
                wheelhouse.resolve(),
            )
            result = _run(
                [str(model_python), "-I", "-X", "utf8", "-c", _MODEL_CHILD], cwd=cwd
            )
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            report["profiles"]["model_transport"] = {
                "status": "PASS",
                "result": json.loads(result.stdout),
            }
        except (
            OSError,
            RuntimeError,
            ValueError,
            json.JSONDecodeError,
            subprocess.SubprocessError,
        ) as exc:
            report["profiles"]["model_transport"] = {
                "status": "FAIL",
                "error": str(exc),
            }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path)
    args = parser.parse_args()
    report = verify(args.delivery, args.work_dir, args.wheelhouse)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report, sort_keys=True))
    return (
        0
        if all(item["status"] != "FAIL" for item in report["profiles"].values())
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
