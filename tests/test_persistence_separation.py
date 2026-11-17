"""Real storage separation and delivery checks, without production connections."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from app.persistence import database
from app.demo_data import database as demo_database
from app.demo_data.seed import generate_database

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_module_release  # noqa: E402
import module_release  # noqa: E402
from scripts.check_module_boundaries import boundary_errors, load_manifest  # noqa: E402


def storage_environment(root: Path) -> dict[str, str]:
    return {
        "FAB_PROJECT_ENV_FILE": str(root / "missing-project.env"),
        "FAB_WORKSPACE_ENV_FILE": str(root / "missing-workspace.env"),
        "FAB_DATABASE_PATH": str(root / "legacy.db"),
        "FAB_DATABASE_DIR": str(root),
        "FAB_MANUFACTURING_DATABASE_PATH": str(root / "manufacturing.db"),
        "FAB_EQUIPMENT_DATABASE_PATH": str(root / "equipment.db"),
        "FAB_QUALITY_DATABASE_PATH": str(root / "quality.db"),
        "FAB_KNOWLEDGE_DATABASE_PATH": str(root / "knowledge.db"),
        "FAB_AGENT_DATABASE_PATH": str(root / "agent.db"),
    }


class PersistenceSeparationTests(unittest.TestCase):
    def test_storage_dependency_guard_rejects_demo_import_before_execution(self):
        with tempfile.TemporaryDirectory() as raw:
            app = Path(raw) / "app"
            shutil.copytree(
                ROOT / "app", app, ignore=shutil.ignore_patterns("__pycache__")
            )
            module = app / "persistence" / "database.py"
            module.write_bytes(
                module.read_bytes()
                + b"\nfrom app.demo_data import database as fixtures\n"
            )
            errors = boundary_errors(app, load_manifest())
            self.assertTrue(
                any(
                    "app.persistence.database" in error and "app.demo_data" in error
                    for error in errors
                ),
                errors,
            )
            pure = app / "intent_runtime" / "contracts.py"
            pure.write_bytes(
                pure.read_bytes() + b"\nfrom app.persistence import connection\n"
            )
            errors = boundary_errors(app, load_manifest())
            self.assertTrue(
                any(
                    "app.intent_runtime.contracts" in error
                    and "pure module imports forbidden app.persistence.connection"
                    in error
                    for error in errors
                ),
                errors,
            )

    def test_application_initialization_creates_only_owned_state_stores(self):
        with (
            tempfile.TemporaryDirectory() as raw,
            patch.dict(os.environ, storage_environment(Path(raw))),
        ):
            root = Path(raw)
            database.initialize()
            self.assertEqual(
                {p.name for p in root.glob("*.db")}, {"agent.db", "knowledge.db"}
            )
            with database.db_session() as connection:
                names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_temp_master WHERE type='view'"
                    )
                }
                self.assertTrue(
                    {"chat_sessions", "agent_runs", "knowledge_chunks", "model_catalog"}
                    <= names
                )
                self.assertFalse(
                    {"lots", "process_runs", "simulation_metadata", "defect_types"}
                    & names
                )
                for table in ("lots", "simulation_metadata"):
                    with (
                        self.subTest(table=table),
                        self.assertRaises(sqlite3.OperationalError),
                    ):
                        connection.execute(f"SELECT * FROM {table}")
                with self.assertRaises(KeyError):
                    database.writable_table("lots")

    def test_application_state_commits_rolls_back_and_reinitializes_without_business_writes(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as raw,
            patch.dict(os.environ, storage_environment(Path(raw))),
        ):
            root = Path(raw)
            business = root / "manufacturing.db"
            with closing(sqlite3.connect(business)) as connection:
                connection.execute("CREATE TABLE company_sentinel(value TEXT)")
                connection.execute("INSERT INTO company_sentinel VALUES ('untouched')")
                connection.commit()
            before = business.read_bytes()
            database.initialize()
            session_table = database.writable_table("chat_sessions")
            with database.db_session() as connection:
                connection.execute(
                    f"INSERT INTO {session_table}(session_id,title,created_at,updated_at) VALUES ('saved','retained','2026-01-01','2026-01-01')"
                )
                connection.commit()
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                with database.db_session() as connection:
                    connection.execute(
                        f"UPDATE {session_table} SET title='rolled back'"
                    )
                    raise RuntimeError("cancelled")
            database.initialize()
            with database.db_session() as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT title FROM chat_sessions WHERE session_id='saved'"
                    ).fetchone()[0],
                    "retained",
                )
            self.assertEqual(business.read_bytes(), before)
            self.assertFalse((root / "equipment.db").exists())
            self.assertFalse((root / "quality.db").exists())

    def test_explicit_single_application_database_does_not_include_demo_schema(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "application.db"
            database.initialize(path)
            database.initialize(path)
            with database.db_session(path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertIn("personal_knowledge_documents", tables)
                self.assertIn("agent_plan_steps", tables)
                self.assertNotIn("lots", tables)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM model_catalog").fetchone()[
                        0
                    ],
                    0,
                )

    def test_demo_layout_and_generation_remain_explicit(self):
        with (
            tempfile.TemporaryDirectory() as raw,
            patch.dict(os.environ, storage_environment(Path(raw))),
        ):
            root = Path(raw)
            database.initialize()
            self.assertFalse((root / "manufacturing.db").exists())
            demo_database.initialize()
            with demo_database.db_session() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 0
                )
                self.assertGreater(
                    connection.execute("SELECT COUNT(*) FROM defect_types").fetchone()[
                        0
                    ],
                    0,
                )
            generate_database(days=1, seed=7, end_date="2026-12-25")
            with demo_database.db_session() as connection:
                self.assertGreater(
                    connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 0
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT classification FROM simulation_metadata"
                    ).fetchone()[0],
                    "synthetic_non_production",
                )

    def test_real_delivery_runs_without_demo_package_or_repository_imports(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            delivery, virtual = root / "delivery", root / "venv"
            module_release.build(delivery, build_id="application-storage-separation")
            release, members = install_module_release.read(
                delivery, ["application_storage"]
            )
            selected = release["profiles"]["application_storage"]["source_files"]
            self.assertEqual(len(selected), 12)
            self.assertFalse(
                any(path.startswith("app/demo_data/") for path in selected)
            )
            venv.EnvBuilder(with_pip=False).create(virtual)
            python = virtual / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            purelib = Path(
                subprocess.check_output(
                    [
                        str(python),
                        "-I",
                        "-c",
                        "import sysconfig;print(sysconfig.get_paths()['purelib'])",
                    ],
                    text=True,
                ).strip()
            )
            install_module_release.install(
                delivery, purelib, ["application_storage"], python=python
            )
            script = """
import json, sqlite3, sys
from pathlib import Path
from contextlib import closing
from app.persistence import database
from app.persistence.tool_result_store import ToolResultStore
store = ToolResultStore(Path.cwd() / 'results.db')
store.initialize()
scope = dict(tenant_id='tenant', owner_id='owner', session_id='isolated')
reference = store.save(**scope, run_id='run', call_id='call', metadata={'queried_at':'2026-11-15'}, content=[{'value':7}], permit=lambda:True)
store = ToolResultStore(Path.cwd() / 'results.db')
assert store.read(**scope, result_ref=reference, permit=lambda:True)['units'] == [{'value':7}]
store.revoke_session(**scope)
database.initialize()
with database.db_session() as connection:
    connection.execute("INSERT INTO agent.chat_sessions(session_id,title,created_at,updated_at) VALUES ('isolated','outside','2026-01-01','2026-01-01')")
    connection.commit()
database.initialize()
with database.db_session() as connection:
    assert connection.execute("SELECT title FROM chat_sessions").fetchone()[0] == 'outside'
    try:
        connection.execute('SELECT * FROM lots')
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError('business data unexpectedly accessible')
assert not any(name == 'app.demo_data' or name.startswith('app.demo_data.') for name in sys.modules)
assert not (Path(database.__file__).parents[1] / 'demo_data').exists()
print(json.dumps({'module': str(Path(database.__file__).resolve()), 'status': 'PASS'}))
"""
            environment = {**os.environ, **storage_environment(root / "state")}
            result = subprocess.run(
                [str(python), "-I", "-X", "utf8", "-c", script],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(Path(payload["module"]).is_relative_to(purelib))
            self.assertEqual(
                {p.name for p in (root / "state").glob("*.db")},
                {"knowledge.db", "agent.db"},
            )

    def test_installed_runtime_and_storage_survive_a_real_process_restart(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            delivery, virtual = root / "delivery", root / "venv"
            module_release.build(delivery, build_id="mod029-combined-result-access")
            venv.EnvBuilder(with_pip=False).create(virtual)
            python = virtual / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            purelib = Path(
                subprocess.check_output(
                    [
                        str(python),
                        "-I",
                        "-c",
                        "import sysconfig;print(sysconfig.get_paths()['purelib'])",
                    ],
                    text=True,
                ).strip()
            )
            install_module_release.install(
                delivery,
                purelib,
                ["tool_sources", "application_storage"],
                python=python,
            )
            program = r"""
import asyncio,json,sys
from pathlib import Path
from types import SimpleNamespace
from app.persistence import database
from app.persistence.tool_result_store import ToolResultStore,ResultStoreError
from app.agent_runtime.result_access_run import ResultAccessRun
from app.agent_runtime.execution.loop_guard import ToolLoopGuard
from app.agent_runtime.execution.tool_budget import LoopGuardToolBudget
from app.agent_runtime.execution.runtime_contracts import RuntimeContext,ModelToolCall,ModelResponse
from app.agent_runtime.tools.contracts import ToolExecutionLimits,ToolResult,ToolStatus,ToolExecutionState
from app.agent_runtime.tools.definition import ToolDefinition,ToolBinding
from app.agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.agent_runtime.definition import AgentDefinition,ComponentReference
from app.bootstrap.agent_assembly import assemble_agent
from app.planning_runtime.contracts import ExecutionPlan,PlanBudget,AnalysisScopeContract
phase=sys.argv[1]; state=Path.cwd()/'state.db'; result_path=Path.cwd()/'results.db'
database.initialize(state)
principal=SimpleNamespace(tenant_id='tenant',user_id='owner',roles=('analyst',))
scope=dict(tenant_id='tenant',owner_id='owner',session_id='portable-session')
if phase=='save':
    with database.db_session(state) as connection:
        connection.execute("INSERT INTO chat_sessions(session_id,tenant_id,owner_user_id,title,created_at,updated_at) VALUES ('portable-session','tenant','owner','fixture','2026-11-15','2026-11-15')")
        connection.commit()
store=ToolResultStore(result_path);store.initialize()
def authorize():
    with database.db_session(state) as connection:
        return connection.execute("SELECT 1 FROM chat_sessions WHERE session_id=? AND tenant_id=? AND owner_user_id=?",(scope['session_id'],scope['tenant_id'],scope['owner_id'])).fetchone() is not None
plan=ExecutionPlan('portable','1','fixture','unsupported','','',None,None,AnalysisScopeContract('session',(),(),()),(),(),PlanBudget(0,6,6,100,{'*':6},1,1),(),())
guard=ToolLoopGuard(plan)
access=ResultAccessRun(session_id=scope['session_id'],run_id=phase,principal=principal,store=store,enabled=True,authorize=authorize)
class Input:
    @classmethod
    def from_arguments(cls,value):return cls()
    @classmethod
    def json_schema(cls):return {'type':'object','additionalProperties':False}
class Model:
    async def complete(self,*args):raise AssertionError('No model request expected')
class Sink:
    async def emit(self,*args):pass
def handler(value,context):
    assert phase=='save','Re-read must not call the source'
    return ToolResult(context.call_id,'payload','1.0.0',ToolStatus.SUCCEEDED,ToolExecutionState.COMPLETED,
        [{'record':i,'text':'中文'*400} for i in range(30)],row_count=30)
definition=AgentDefinition('portable','1.0.0','analyst','fixture',(ComponentReference('payload','1.0.0'),),ComponentReference('fixture','1.0.0'),ComponentReference('policy','1.0.0'))
application=assemble_agent(definition,model=Model(),events=Sink(),bindings=(ToolBinding(ToolDefinition('payload','1.0.0','fixture',Input,lambda value:value),handler,None),),
    policy=DemoToolPolicy(frozenset({'payload'})),budget_factory=lambda:LoopGuardToolBudget(guard),server_capabilities=frozenset({'payload'}),model_policy_ref=definition.model_policy,policy_ref=definition.default_policy)
run=application.new_run(RuntimeContext(principal,phase,ToolExecutionLimits(remaining_calls=6,max_result_rows=100)),result_access=access)
async def main():
    saved_path=Path.cwd()/'saved.json'
    if phase=='save':
        produced=await run.tool_stage(ModelToolCall('provider','payload','{}'),call_id='server')
        assert len(produced.value.data)==30
        reference=access.notices[0]['result_ref']
        run.begin_synthesis()
        page=(await access.read({'result_ref':reference,'limit':1}))
        assert page['units'][0]['record']==0
        saved_path.write_text(json.dumps({'reference':reference,'cursor':page['next_cursor'],'queried_at':page['queried_at']}),encoding='utf8')
    else:
        saved=json.loads(saved_path.read_text(encoding='utf8'))
        run.begin_synthesis()
        read=await run.tool_stage(ModelToolCall('read-provider','read_tool_result',json.dumps({'result_ref':saved['reference'],'cursor':saved['cursor'],'limit':1})),call_id='read-server')
        assert read.value.data['units'][0]['record']==1
        assert read.value.data['queried_at']==saved['queried_at']
        assert guard.total_calls==1 and not guard.tool_calls
        store.revoke_session(**scope)
        with database.db_session(state) as connection:
            connection.execute('DELETE FROM chat_sessions WHERE session_id=?',(scope['session_id'],));connection.commit()
        try:store.read(**scope,result_ref=saved['reference'],permit=lambda:True)
        except ResultStoreError:pass
        else:raise AssertionError('Deleted snapshot readable')
    run.close()
asyncio.run(main())
prefix=Path(sys.argv[2]).resolve()
assert all(Path(module.__file__).resolve().is_relative_to(prefix) for name,module in sys.modules.items() if name.startswith('app.') and getattr(module,'__file__',None))
print(json.dumps({'status':'PASS','phase':phase,'module':str(Path(database.__file__).resolve())}))
"""
            environment = {**os.environ, **storage_environment(root / "unused-state")}
            for phase in ("save", "read-delete"):
                completed = subprocess.run(
                    [
                        str(python),
                        "-I",
                        "-X",
                        "utf8",
                        "-c",
                        program,
                        phase,
                        str(purelib),
                    ],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(json.loads(completed.stdout)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
