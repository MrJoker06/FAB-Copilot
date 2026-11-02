from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SkillPortableTests(unittest.TestCase):
    def test_skill_core_runs_from_isolated_source_copy(self) -> None:
        source = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "isolated"
            (copied / "app" / "skills").mkdir(parents=True)
            (copied / "app" / "__init__.py").write_text(
                (source / "app/__init__.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            names = (
                "__init__.py",
                "contracts.py",
                "manifest.py",
                "package.py",
                "resources.py",
                "versions.py",
            )
            for name in names:
                shutil.copy2(source / "app/skills" / name, copied / "app/skills" / name)
            shutil.copytree(
                source / "evaluations/skills/manifest_validation_v1", copied / "fixture"
            )
            inventory = {
                "tools": {"get_equipment_health": "1.0.0"},
                "workflows": {"fixture-workflow": "1.0.0"},
                "evidence_policies": {"fixture-evidence-policy": "1.0.0"},
            }
            code = """
import builtins, json, os, pathlib, re, stat, sys, unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
sys.path.insert(0, sys.argv[1])
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    forbidden = {'socket', 'sqlite3', 'subprocess'}
    if name.split('.', 1)[0] in forbidden or (name.startswith('app') and not (name == 'app.skills' or name.startswith('app.skills.'))):
        raise ImportError('guarded import')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
os.getenv = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('guarded environment'))
os.system = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('guarded system'))
class EnvironmentGuard(dict):
    def __getitem__(self, key): raise RuntimeError('guarded environment')
    def get(self, key, default=None): raise RuntimeError('guarded environment')
    def __setitem__(self, key, value): raise RuntimeError('guarded environment')
os.environ = EnvironmentGuard()
for operation in (lambda: __import__('socket'), lambda: __import__('sqlite3'), lambda: __import__('subprocess'), lambda: __import__('app.core'), lambda: __import__('app.skills_extra'), lambda: os.getenv('HOME'), lambda: os.environ['HOME'], lambda: os.environ.__setitem__('X', '1'), lambda: os.system('echo forbidden')):
    try:
        operation()
    except (ImportError, RuntimeError):
        pass
    else:
        raise AssertionError('negative control did not trigger')
from app.skills import DependencyInventory, SkillPackage
p = SkillPackage.open(sys.argv[2], DependencyInventory(**json.loads(sys.argv[3])))
loaded = p.read_resources(('SKILL.md',))[0]
origins = [value.__file__ for name, value in sys.modules.items() if (name == 'app' or name == 'app.skills' or name.startswith('app.skills.')) and getattr(value, '__file__', None)]
print(json.dumps({'skill_id': p.manifest.skill_id, 'path': loaded.path, 'origins': origins}))
"""
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    code,
                    str(copied),
                    str(copied / "fixture"),
                    json.dumps(inventory),
                ],
                cwd=temporary,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            result_value = json.loads(result.stdout)
            self.assertEqual(result_value["skill_id"], "manifest-validation")
            self.assertEqual(result_value["path"], "SKILL.md")
            self.assertTrue(result_value["origins"])
            self.assertTrue(
                all(
                    Path(origin).resolve().is_relative_to(copied.resolve())
                    for origin in result_value["origins"]
                )
            )

    def test_cli_direct_and_module_forms_return_sanitized_errors(self) -> None:
        source = Path.cwd()
        fixture = source / "evaluations/skills/manifest_validation_v1"
        inventory = source / "evaluations/skills/manifest_validation_inventory_v1.json"
        with tempfile.TemporaryDirectory() as temporary:
            direct = subprocess.run(
                [
                    sys.executable,
                    str(source / "scripts/check_skill_package.py"),
                    "--package",
                    str(fixture),
                    "--inventory",
                    str(inventory),
                ],
                cwd=temporary,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(direct.returncode, 0, direct.stderr)
            self.assertFalse(json.loads(direct.stdout)["execution_authorized"])
            bad = Path(temporary) / "bad.json"
            bad.write_text('{"tools":{},"tools":{}}', encoding="utf-8")
            environment = dict(os.environ, PYTHONPATH=str(source))
            module = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.check_skill_package",
                    "--package",
                    str(fixture),
                    "--inventory",
                    str(bad),
                ],
                cwd=temporary,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(module.returncode, 2)
            self.assertEqual(
                json.loads(module.stderr)["error_code"], "invalid_inventory"
            )


if __name__ == "__main__":
    unittest.main()
