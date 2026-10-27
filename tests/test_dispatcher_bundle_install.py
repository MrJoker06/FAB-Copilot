"""End-to-end installation smoke coverage for the isolated dispatcher bundle."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path

from scripts.build_portable_unit import build_unit, load_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluations" / "mod_007_dispatcher_bundle_v1.json"
INSTALLER = ROOT / "scripts" / "install_dispatcher_bundle.py"


class DispatcherBundleInstallTests(unittest.TestCase):
    def _venv_python(self, root: Path) -> Path:
        return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def _install(self, work: Path) -> tuple[Path, Path]:
        bundle = build_unit(
            "dispatcher_pilot",
            load_manifest(MANIFEST)["units"]["dispatcher_pilot"],
            work,
        )
        environment = work / "venv"
        venv.EnvBuilder(with_pip=False).create(environment)
        python = self._venv_python(environment)
        purelib = subprocess.check_output(
            [
                str(python),
                "-I",
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ],
            text=True,
        ).strip()
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(INSTALLER),
                "--bundle",
                str(bundle),
                "--target",
                purelib,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return python, Path(purelib)

    def _demo(
        self, python: Path, cwd: Path, *arguments: str
    ) -> tuple[int, dict[str, object]]:
        completed = subprocess.run(
            [str(python), "-I", "-m", "app.bootstrap.dispatcher_demo", *arguments],
            cwd=cwd,
            env={},
            text=True,
            capture_output=True,
            check=False,
        )
        return completed.returncode, json.loads(completed.stdout)

    def test_installed_bundle_runs_fake_demo_without_repository_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            python, purelib = self._install(work)
            unrelated = work / "unrelated"
            unrelated.mkdir()
            code, payload = self._demo(python, unrelated)
            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["result"]["status"], "succeeded")
            code, payload = self._demo(
                python, unrelated, "--arguments", '{"equipment_id":"demo-01"}'
            )
            self.assertEqual(code, 0, payload)
            self.assertEqual(payload["result"]["status"], "succeeded")
            code, payload = self._demo(
                python,
                unrelated,
                "--tool",
                "query_manufacturing_data",
                "--arguments",
                '{"sql":"secret"}',
            )
            self.assertEqual(code, 2)
            self.assertEqual(payload["result"]["status"], "denied")
            self.assertEqual(payload["guard"]["total_calls"], 0)
            code, payload = self._demo(python, unrelated, "--arguments", "[]")
            self.assertEqual(code, 2)
            self.assertEqual(payload["result"]["status"], "invalid_arguments")
            self.assertEqual(payload["guard"]["total_calls"], 0)
            probe = subprocess.check_output(
                [
                    str(python),
                    "-I",
                    "-c",
                    "import app,sys; print(app.__file__); print(sys.prefix != sys.base_prefix)",
                ],
                cwd=unrelated,
                env={},
                text=True,
            ).splitlines()
            self.assertTrue(Path(probe[0]).resolve().is_relative_to(purelib.resolve()))
            self.assertEqual(probe[1], "True")

    def test_all_loaded_app_modules_are_from_declared_install_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            python, purelib = self._install(work)
            unrelated = work / "unrelated"
            unrelated.mkdir()
            inventory = json.loads(MANIFEST.read_text())["units"]["dispatcher_pilot"][
                "files"
            ]
            code = (
                "import json,pathlib,runpy,sys\n"
                "module=runpy.run_module('app.bootstrap.dispatcher_demo',run_name='notmain',alter_sys=True)\n"
                "assert module['main']([])==0\n"
                "root=pathlib.Path(sysconfig.get_path('purelib')).resolve()\n"
                "bad=[]\n"
                "for name,item in sys.modules.items():\n"
                " p=getattr(item,'__file__',None)\n"
                " if (name=='app' or name.startswith('app.')) and p and not pathlib.Path(p).resolve().is_relative_to(root): bad.append((name,p))\n"
                "assert not bad,bad\n"
            )
            code = "import sysconfig\n" + code
            completed = subprocess.run(
                [str(python), "-I", "-c", code],
                cwd=unrelated,
                env={},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(
                all((purelib / relative).exists() for relative in inventory)
            )

    def test_installed_sqlite_adapter_and_preexecution_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            python, _ = self._install(work)
            unrelated = work / "unrelated"
            unrelated.mkdir()
            manufacturing, equipment = work / "m.db", work / "e.db"
            with sqlite3.connect(manufacturing) as connection:
                connection.execute(
                    "CREATE TABLE process_runs (equipment_id,process_step,run_time,excursion_code,defect_density,pass_flag)"
                )
                connection.execute(
                    "INSERT INTO process_runs VALUES ('DEMO-01','CMP','2026-10-24',NULL,.1,1)"
                )
            with sqlite3.connect(equipment) as connection:
                connection.execute(
                    "CREATE TABLE equipment_events (equipment_id,event_time,duration_minutes)"
                )
                connection.execute(
                    "INSERT INTO equipment_events VALUES ('DEMO-01','2026-10-24',3)"
                )
            common = (
                "--adapter",
                "sqlite",
                "--manufacturing-db",
                str(manufacturing),
                "--equipment-db",
                str(equipment),
            )
            code, payload = self._demo(python, unrelated, *common)
            self.assertEqual(code, 0, payload)
            missing = work / "missing.db"
            code, payload = self._demo(
                python,
                unrelated,
                "--adapter",
                "sqlite",
                "--manufacturing-db",
                str(missing),
                "--equipment-db",
                str(equipment),
            )
            self.assertEqual(code, 2)
            self.assertFalse(missing.exists())
            for extra in (
                ("--role", "viewer"),
                ("--tenant-id", "wrong"),
                ("--max-tool-calls", "0"),
                ("--timeout-ms", "0"),
            ):
                code, payload = self._demo(python, unrelated, *extra)
                self.assertEqual(code, 2)
                self.assertEqual(payload["guard"]["total_calls"], 0)

    def test_installed_fake_has_active_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            python, _purelib = self._install(work)
            unrelated = work / "unrelated"
            unrelated.mkdir()
            inventory = json.loads(MANIFEST.read_text())["units"]["dispatcher_pilot"][
                "files"
            ]
            script = """import asyncio, importlib, importlib.abc, os, pathlib, runpy, socket, sqlite3, sys
ROOT=pathlib.Path(sysconfig.get_path('purelib')).resolve()
INVENTORY=set(sys.argv[1:])
blocked=[]
imports=[]
def audit(event, args):
    if event in {'sqlite3.connect','socket.connect','socket.getaddrinfo','socket.gethostbyname'}:
        blocked.append(event); raise AssertionError(event)
sys.addaudithook(audit)
for action in (lambda: sqlite3.connect(':memory:'), lambda: socket.getaddrinfo('invalid', 1), lambda: socket.socket().connect(('127.0.0.1', 1))):
    try: action()
    except AssertionError: pass
    else: raise AssertionError('negative network/database control')
assert blocked; blocked.clear()
class Deny(importlib.abc.MetaPathFinder):
    prefixes=('app.core.settings','app.manufacturing.reports','app.agent_runtime.tools.registry','app.agent_runtime.tools.catalog','app.model_gateway','app.evidence','app.persistence')
    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.prefixes[0] or fullname.startswith(self.prefixes): imports.append(fullname); raise AssertionError(fullname)
sys.meta_path.insert(0, Deny())
try: importlib.import_module('app.manufacturing.reports')
except AssertionError: pass
else: raise AssertionError('negative import control')
assert imports and imports[-1] == 'app.manufacturing.reports'; imports.clear()
class Env(dict):
    allowed={'PYTHONASYNCIODEBUG','COLUMNS','LINES','TERM','LANG','LANGUAGE'}
    def __getitem__(self, key):
        if key not in self.allowed and not key.startswith('LC_'): raise AssertionError(key)
        return ''
    def get(self, key, default=None): return self[key] if key in self.allowed or key.startswith('LC_') else (_ for _ in ()).throw(AssertionError(key))
    def __iter__(self): raise AssertionError('environment iteration')
guard=Env(); os.environ=guard
try: os.getenv('FAB_DATABASE_PATH')
except AssertionError: pass
else: raise AssertionError('negative environment control')
module=runpy.run_module('app.bootstrap.dispatcher_demo', run_name='notmain', alter_sys=True)
assert module['main']([]) == 0
root=ROOT
for name, item in sys.modules.items():
    location=getattr(item, '__file__', None)
    if (name == 'app' or name.startswith('app.')) and location:
        relative=pathlib.Path(location).resolve().relative_to(root).as_posix()
        assert relative in INVENTORY, (name, relative)
assert not blocked and not imports, (blocked, imports)
"""
            script = "import sysconfig\n" + script
            completed = subprocess.run(
                [str(python), "-I", "-c", script, *inventory],
                cwd=unrelated,
                env={},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
