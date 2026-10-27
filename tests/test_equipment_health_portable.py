from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "evaluations" / "mod_005_equipment_health_source_v1.json"


class EquipmentHealthPortableTests(unittest.TestCase):
    def _copy_unit(self, target: Path) -> None:
        inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
        for relative in inventory["files"]:
            source, destination = ROOT / relative, target / relative
            self.assertTrue(source.is_file(), relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def _databases(self, root: Path) -> tuple[Path, Path]:
        manufacturing, equipment = (
            root / "manufacturing #?.db",
            root / "equipment #?.db",
        )
        with sqlite3.connect(manufacturing) as connection:
            connection.execute(
                "CREATE TABLE process_runs (equipment_id, process_step, run_time, excursion_code, defect_density, pass_flag)"
            )
            connection.execute(
                "INSERT INTO process_runs VALUES ('CMP-01','CMP','2026-10-02',NULL,0.1,1)"
            )
        with sqlite3.connect(equipment) as connection:
            connection.execute(
                "CREATE TABLE equipment_events (equipment_id, event_time, duration_minutes)"
            )
        return manufacturing, equipment

    def _run(self, unit: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        allowed = json.loads(INVENTORY.read_text(encoding="utf-8"))["files"]
        runner = f"""import argparse, builtins, os, runpy, shutil, socket, sys
from pathlib import Path
unit = Path({str(unit)!r}).resolve()
allowed_files = set({allowed!r})
blocked = ('app.core.settings','app.persistence','app.manufacturing.reports','app.knowledge','app.agent_runtime.service','app.agent_runtime.tools.catalog','app.agent_runtime.tools.registry')
old_import = builtins.__import__
argparse.ArgumentParser()
argparse._ = lambda value: value
shutil.get_terminal_size = lambda fallback=(80, 24): os.terminal_size(fallback)
def guard_import(name, *args, **kwargs):
    if any(name == item or name.startswith(item + '.') for item in blocked):
        raise AssertionError('blocked import')
    return old_import(name, *args, **kwargs)
class DenyEnvironment(dict):
    def __getitem__(self, key): raise AssertionError('environment read')
    def get(self, key, default=None): raise AssertionError('environment read')
    def __iter__(self): raise AssertionError('environment read')
builtins.__import__ = guard_import
os.environ = DenyEnvironment()
os.getenv = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('environment read'))
socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network'))
for control in (lambda: guard_import('app.persistence'), lambda: os.environ.get('FAB_DATABASE_PATH'), lambda: os.getenv('FAB_DATABASE_PATH'), lambda: socket.socket()):
    try: control()
    except AssertionError: pass
    else: raise AssertionError('negative control did not reject')
sys.argv = ['demo_equipment_health.py', *{list(arguments)!r}]
code = 0
try:
    runpy.run_path({str(unit / "scripts/demo_equipment_health.py")!r}, run_name='__main__')
except SystemExit as error:
    code = error.code
for name, module in list(sys.modules.items()):
    if name == 'app' or name.startswith('app.'):
        origin = Path(module.__file__).resolve()
        assert origin.is_relative_to(unit), origin
        assert origin.relative_to(unit).as_posix() in allowed_files, origin
assert not any(name in sys.modules for name in blocked)
if '--adapter' not in sys.argv or 'fake' in sys.argv:
    assert 'app.integrations.manufacturing.sqlite_equipment_health' not in sys.modules
sys.exit(code)
"""
        return subprocess.run(
            [sys.executable, "-I", "-S", "-c", runner],
            text=True,
            capture_output=True,
            check=False,
            cwd=unit,
            env={},
        )

    def test_copied_unit_runs_fake_sqlite_and_invalid_without_repo_imports(self):
        with tempfile.TemporaryDirectory() as raw:
            unit = Path(raw) / "unit"
            self._copy_unit(unit)
            manufacturing, equipment = self._databases(unit)
            fake = self._run(unit, "--as-of", "2026-10-24")
            self.assertEqual(fake.returncode, 0, fake.stderr)
            self.assertEqual(
                json.loads(fake.stdout)["sources"][0]["source_kind"], "fake"
            )
            sqlite = self._run(
                unit,
                "--adapter",
                "sqlite",
                "--as-of",
                "2026-10-24",
                "--manufacturing-db",
                str(manufacturing),
                "--equipment-db",
                str(equipment),
            )
            self.assertEqual(sqlite.returncode, 0, sqlite.stderr)
            self.assertEqual(
                json.loads(sqlite.stdout)["sources"][0]["source_kind"], "sqlite"
            )
            invalid = self._run(unit, "--arguments", '{"sql":"select 1"}')
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(json.loads(invalid.stdout)["status"], "invalid_arguments")
            malformed = self._run(unit, "--arguments", "{")
            self.assertEqual(malformed.returncode, 2)
            missing = self._run(
                unit,
                "--adapter",
                "sqlite",
                "--manufacturing-db",
                str(unit / "missing.db"),
                "--equipment-db",
                str(equipment),
            )
            self.assertEqual(missing.returncode, 3)
            self.assertEqual(
                json.loads(missing.stdout)["error"]["code"], "SOURCE_FAILURE"
            )
            self.assertNotIn("missing.db", missing.stdout + missing.stderr)
            self.assertEqual(
                {path.name for path in unit.glob("*.db")},
                {manufacturing.name, equipment.name},
            )
            self.assertFalse((unit / ".env").exists())
            self.assertFalse((unit / "logs").exists())
