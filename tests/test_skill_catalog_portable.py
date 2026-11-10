from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.skills.contracts import SkillPackageError


class SkillCatalogPortableTests(unittest.TestCase):
    def test_catalog_discovery_loader_runs_from_exact_isolated_copy(self) -> None:
        source = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "isolated"
            (copied / "app" / "skills").mkdir(parents=True)
            shutil.copy2(source / "app" / "__init__.py", copied / "app" / "__init__.py")
            names = (
                "__init__.py",
                "contracts.py",
                "versions.py",
                "frontmatter.py",
                "manifest.py",
                "resources.py",
                "package.py",
                "catalog.py",
                "discovery.py",
                "loader.py",
            )
            for name in names:
                shutil.copy2(
                    source / "app" / "skills" / name, copied / "app" / "skills" / name
                )
            shutil.copytree(
                source / "evaluations" / "skills" / "catalog_discovery_v1",
                copied / "fixture",
            )
            code = """
import builtins, json, os, pathlib, re, stat, sys, unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
sys.path.insert(0, sys.argv[1])
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.', 1)[0] in {'socket', 'sqlite3', 'subprocess'} or (name.startswith('app') and not (name == 'app.skills' or name.startswith('app.skills.'))):
        raise ImportError('guarded')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
os.getenv = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('environment'))
os.system = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('system'))
class EnvironmentGuard(dict):
    def __getitem__(self, key): raise RuntimeError('environment')
    def __setitem__(self, key, value): raise RuntimeError('environment')
    def get(self, key, default=None): raise RuntimeError('environment')
os.environ = EnvironmentGuard()
for operation in (lambda: __import__('socket'), lambda: __import__('sqlite3'), lambda: __import__('subprocess'), lambda: __import__('app.core'), lambda: __import__('app.skills_extra'), lambda: os.getenv('HOME'), lambda: os.environ['HOME'], lambda: os.environ.__setitem__('X', '1'), lambda: os.system('x')):
    try: operation()
    except (ImportError, RuntimeError): pass
    else: raise AssertionError('negative control')
from app.skills.catalog import SkillCatalog, SkillReference
from app.skills.contracts import DependencyInventory, SkillPackageError
from app.skills.discovery import DiscoveryQuery, discover
from app.skills.loader import SkillLoader
inventory = DependencyInventory({'get_equipment_health':'1.0.0'}, {'fixture-workflow':'1.0.0'}, {'fixture-evidence-policy':'1.0.0'})
catalog = SkillCatalog.build((sys.argv[2],), inventory)
result = discover(catalog, DiscoveryQuery('fixture-workflow', 'LITHO', 'ready', frozenset({'lot_id'})))
loader = SkillLoader(catalog)
snapshot = loader.load(result.candidates[0].reference)
snapshot = loader.expand(snapshot, ('references/catalog.md',))
if [x.path for x in snapshot.loaded_resources] != ['SKILL.md', 'references/catalog.md']: raise AssertionError('incremental load failed')
missing = SkillCatalog.build((sys.argv[2],), DependencyInventory({}, {'fixture-workflow':'1.0.0'}, {'fixture-evidence-policy':'1.0.0'}))
if missing.entries[0].unavailable_reason != 'missing_dependency': raise AssertionError('missing dependency accepted')
from app.skills.manifest import parse_manifest
try: parse_manifest('{"bad":true}')
except SkillPackageError: pass
else: raise AssertionError('malformed manifest accepted')
try: catalog.find(SkillReference('catalog-validation', '9.0.0'))
except SkillPackageError: pass
else: raise AssertionError('unknown reference accepted')
origins = [value.__file__ for name, value in sys.modules.items() if (name == 'app' or name.startswith('app.skills')) and getattr(value, '__file__', None)]
print(json.dumps({'loaded':[x.path for x in snapshot.loaded_resources], 'origins':origins}))
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
                ],
                cwd=temporary,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value["loaded"], ["SKILL.md", "references/catalog.md"])
            expected = {
                (copied / "app" / "__init__.py").resolve(),
                *{(copied / "app" / "skills" / name).resolve() for name in names},
            }
            self.assertEqual(
                {Path(origin).resolve() for origin in value["origins"]}, expected
            )

    def test_cli_distinguishes_query_mismatch_from_unavailable_skill(self) -> None:
        source = Path.cwd()
        command = [
            sys.executable,
            str(source / "scripts" / "demo_skill_loading.py"),
            "--package",
            str(source / "evaluations" / "skills" / "catalog_discovery_v1"),
            "--inventory",
            str(
                source
                / "evaluations"
                / "skills"
                / "catalog_discovery_inventory_v1.json"
            ),
            "--skill-id",
            "catalog-validation",
            "--version",
            "1.0.0",
            "--process-step",
            "CMP",
        ]
        mismatch = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(mismatch.returncode, 2)
        self.assertEqual(
            json.loads(mismatch.stderr)["error_code"], "selection_no_match"
        )
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "skill"
            shutil.copytree(
                source / "evaluations" / "skills" / "catalog_discovery_v1", copied
            )
            manifest = json.loads(
                (copied / "manifest.json").read_text(encoding="utf-8")
            )
            manifest["status"] = "disabled"
            (copied / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            unavailable = subprocess.run(
                [*command[:3], str(copied), *command[4:]],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(unavailable.returncode, 2)
            self.assertEqual(
                json.loads(unavailable.stderr)["error_code"], "ineligible_status"
            )

    def test_cli_rejects_unselected_resources_and_invalid_inventory_files(self) -> None:
        source = Path.cwd()
        command = [
            sys.executable,
            str(source / "scripts" / "demo_skill_loading.py"),
            "--package",
            str(source / "evaluations" / "skills" / "catalog_discovery_v1"),
            "--inventory",
            str(
                source
                / "evaluations"
                / "skills"
                / "catalog_discovery_inventory_v1.json"
            ),
            "--resource",
            "references/catalog.md",
        ]
        resource = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(resource.returncode, 2)
        self.assertEqual(json.loads(resource.stderr)["error_code"], "invalid_selection")
        from scripts.check_skill_package import load_inventory

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, content in (
                ("bad-utf8.json", b"\xff"),
                ("duplicate.json", b'{"tools":{},"tools":{}}'),
                ("oversized.json", b"x" * (128 * 1024 + 1)),
            ):
                path = root / name
                path.write_bytes(content)
                with (
                    self.subTest(name=name),
                    self.assertRaises(SkillPackageError) as error,
                ):
                    load_inventory(path)
                self.assertEqual(
                    getattr(error.exception, "code", None), "invalid_inventory"
                )


if __name__ == "__main__":
    unittest.main()
