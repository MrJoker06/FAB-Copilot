from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_modularization_boundaries as boundaries


class ModularizationBoundaryTests(unittest.TestCase):
    def _project(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "app").mkdir()
        (root / "app" / "__init__.py").write_text("", encoding="utf-8")
        (root / "evaluations").mkdir()
        (root / "evaluations" / "portable_units_v1.json").write_text(
            '{"units": {}}', encoding="utf-8"
        )
        return root

    def _manifest(self, root: Path, files: list[dict] | None = None) -> dict:
        manifest = {
            "schema_version": 1,
            "files": files
            or [
                {
                    "path": "app/__init__.py",
                    "primary_module": "application_bootstrap",
                    "artifact_group": "application_bundle",
                }
            ],
            "allowed_dependencies": {
                name: list(boundaries.MODULES) for name in boundaries.MODULES
            },
            "dependency_debt": [],
            "portable_overlaps": [],
            "compatibility_ledger": [],
            "compatibility_consumers": [],
            "database_candidates": [],
            "database_ledger": {"sources": []},
        }
        return manifest

    def test_valid_ownership(self):
        root = self._project()
        self.assertEqual(boundaries.ownership_errors(root, self._manifest(root)), [])

    def test_noncanonical_path_is_rejected(self):
        root = self._project()
        manifest = self._manifest(
            root,
            [
                {
                    "path": "../app/a.py",
                    "primary_module": "runtime",
                    "artifact_group": "x",
                }
            ],
        )
        self.assertTrue(
            any(
                "non-canonical" in item
                for item in boundaries.ownership_errors(root, manifest)
            )
        )

    def test_unknown_module_is_rejected(self):
        root = self._project()
        manifest = self._manifest(
            root,
            [
                {
                    "path": "app/__init__.py",
                    "primary_module": "unknown",
                    "artifact_group": "x",
                }
            ],
        )
        self.assertTrue(
            any(
                "unknown logical" in item
                for item in boundaries.ownership_errors(root, manifest)
            )
        )

    def test_duplicate_owner_is_rejected(self):
        root = self._project()
        entries = [
            {
                "path": "app/__init__.py",
                "primary_module": "runtime",
                "artifact_group": "x",
            }
        ] * 2
        self.assertTrue(
            any(
                "duplicate" in item
                for item in boundaries.ownership_errors(
                    root, self._manifest(root, entries)
                )
            )
        )

    def test_missing_owner_is_rejected(self):
        root = self._project()
        (root / "app" / "a.py").write_text("", encoding="utf-8")
        self.assertTrue(
            any(
                "ownership missing" in item
                for item in boundaries.ownership_errors(root, self._manifest(root))
            )
        )

    def test_orphan_owner_is_rejected(self):
        root = self._project()
        entries = self._manifest(root)["files"] + [
            {"path": "app/gone.py", "primary_module": "runtime", "artifact_group": "x"}
        ]
        self.assertTrue(
            any(
                "stale ownership" in item
                for item in boundaries.ownership_errors(
                    root, self._manifest(root, entries)
                )
            )
        )

    def test_new_dependency_debt_is_rejected(self):
        root = self._project()
        (root / "app" / "a.py").write_text("import app.b\n", encoding="utf-8")
        (root / "app" / "b.py").write_text("", encoding="utf-8")
        entries = self._manifest(root)["files"] + [
            {"path": "app/a.py", "primary_module": "runtime", "artifact_group": "x"},
            {
                "path": "app/b.py",
                "primary_module": "integrations",
                "artifact_group": "x",
            },
        ]
        manifest = self._manifest(root, entries)
        manifest["allowed_dependencies"]["runtime"] = ["runtime"]
        self.assertTrue(
            any(
                "new dependency debt" in item
                for item in boundaries.dependency_errors(root, manifest)
            )
        )

    def test_stale_dependency_debt_is_rejected(self):
        root = self._project()
        manifest = self._manifest(root)
        manifest["dependency_debt"] = [
            {
                "source": "app.a",
                "target": "app.b",
                "reason": "x",
                "exit_task": "MOD-004",
            }
        ]
        self.assertTrue(
            any(
                "stale dependency" in item
                for item in boundaries.dependency_errors(root, manifest)
            )
        )

    def test_portable_overlap_drift_is_rejected(self):
        root = self._project()
        (root / "evaluations" / "portable_units_v1.json").write_text(
            json.dumps(
                {
                    "units": {
                        "one": {"files": ["app/__init__.py"]},
                        "two": {"files": ["app/__init__.py"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(boundaries.portable_errors(root, self._manifest(root)))

    def test_database_candidate_drift_is_rejected(self):
        root = self._project()
        (root / "app" / "a.py").write_text(
            "connection.execute('SELECT * FROM lots')\n", encoding="utf-8"
        )
        self.assertEqual(
            boundaries.database_errors(root, self._manifest(root)),
            ["database candidate drift"],
        )

    def test_manifest_schema_is_fail_closed(self):
        root = self._project()
        path = root / "bad.json"
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            boundaries.load_manifest(path)

    def test_consumer_inventory_resolves_alias_dynamic_relative_and_patch_forms(self):
        root = self._project()
        (root / "tests").mkdir()
        (root / "tests" / "consumer.py").write_text(
            "import importlib as loader\nfrom app.agent_runtime import service as agent\n"
            "from unittest import mock\nloader.import_module('app.agent_runtime.service')\n"
            "mock.patch('app.agent_runtime.service.emit')\n"
            "mock.patch.object(agent, 'run_agent')\nmock.patch.dict(agent.TOOL_HANDLERS, {})\n",
            encoding="utf-8",
        )
        found = boundaries._literal_consumers(root, {"app.agent_runtime.service"})
        self.assertEqual(
            {item["kind"] for item in found},
            {"import", "dynamic_import", "patch", "patch.object", "patch.dict"},
            found,
        )

    def test_consumer_inventory_resolves_relative_import(self):
        root = self._project()
        (root / "app" / "agent_runtime").mkdir()
        (root / "app" / "agent_runtime" / "__init__.py").write_text(
            "", encoding="utf-8"
        )
        (root / "app" / "agent_runtime" / "consumer.py").write_text(
            "from . import service\n", encoding="utf-8"
        )
        found = boundaries._literal_consumers(root, {"app.agent_runtime.service"})
        self.assertEqual(found[0]["symbol"], "app.agent_runtime.service")

    def test_malformed_dependency_does_not_raise(self):
        root = self._project()
        manifest = self._manifest(root)
        manifest["allowed_dependencies"] = {"runtime": {"bad": "shape"}}
        self.assertTrue(boundaries.dependency_errors(root, manifest))

    def test_compatibility_duplicate_and_unknown_owner_are_rejected(self):
        root = self._project()
        item = {field: "value" for field in boundaries.REQUIRED_COMPATIBILITY_FIELDS}
        item.update(entrypoint="app.x", owner="unknown")
        manifest = self._manifest(root)
        manifest["compatibility_ledger"] = [item, dict(item)]
        self.assertTrue(boundaries.compatibility_errors(root, manifest))

    def test_database_import_candidate_is_snapshotted(self):
        root = self._project()
        (root / "app" / "a.py").write_text(
            "from app.persistence.database import db_session\n", encoding="utf-8"
        )
        self.assertEqual(
            boundaries.database_candidates(root)[0]["imports"],
            ["app.persistence.database.db_session"],
        )

    def test_complete_valid_fake_project(self):
        root = self._project()
        self.assertEqual(boundaries.validate(root, self._manifest(root)), [])

    def test_real_repository_has_narrow_target_policy_and_exact_inventory(self):
        manifest = boundaries.load_manifest()
        self.assertEqual(boundaries.validate(boundaries.PROJECT_DIR, manifest), [])
        policy = manifest["allowed_dependencies"]
        self.assertNotIn("business_tools", policy["tool_system"])
        for module in ("integrations", "persistence", "application_bootstrap"):
            self.assertNotIn(module, policy["runtime"])
        self.assertEqual(
            policy["manufacturing_domain"],
            ["core_contracts_configuration", "manufacturing_domain"],
        )

    def test_nested_bad_shapes_return_errors_instead_of_type_errors(self):
        root = self._project()
        base = self._manifest(root)
        cases = []
        bad = copy.deepcopy(base)
        bad["allowed_dependencies"]["runtime"] = [{}]
        cases.append((bad, "allowed_dependencies"))
        bad = copy.deepcopy(base)
        bad["files"][0].update(status="transitional", split_targets=[{}])
        cases.append((bad, "transitional"))
        bad = copy.deepcopy(base)
        bad["compatibility_ledger"] = [
            {field: [] for field in boundaries.REQUIRED_COMPATIBILITY_FIELDS}
        ]
        cases.append((bad, "compatibility ledger values"))
        bad = copy.deepcopy(base)
        bad["database_ledger"]["sources"] = [{"source_file": []}]
        cases.append((bad, "database ledger"))
        for manifest, expected in cases:
            with self.subTest(expected=expected):
                self.assertTrue(
                    any(
                        expected in error
                        for error in boundaries.validate(root, manifest)
                    )
                )

    def test_static_symlink_is_rejected(self):
        root = self._project()
        (root / "app" / "static").mkdir()
        (root / "app" / "static" / "bad.js").symlink_to(root / "missing")
        self.assertTrue(
            any(
                "symlink rejected" in error
                for error in boundaries.validate(root, self._manifest(root))
            )
        )

    def test_duplicate_overlap_is_rejected(self):
        root = self._project()
        manifest = self._manifest(root)
        record = {
            "path": "app/__init__.py",
            "unique_owner": "application_bundle",
            "reason": "temporary isolated validation overlap",
        }
        manifest["portable_overlaps"] = [record, dict(record)]
        self.assertIn(
            "duplicate or invalid portable overlap path",
            boundaries.portable_errors(root, manifest),
        )

    def test_consumer_new_and_stale_are_rejected_separately(self):
        root = self._project()
        manifest = self._manifest(root)
        symbol = "app.agent_runtime.service"
        record = {
            field: "reviewed" for field in boundaries.REQUIRED_COMPATIBILITY_FIELDS
        }
        record.update(entrypoint=symbol, owner="runtime")
        manifest["compatibility_ledger"] = [record]
        (root / "app" / "consumer.py").write_text(
            "from app.agent_runtime.service import run_agent\n", encoding="utf-8"
        )
        errors = boundaries.compatibility_errors(root, manifest)
        self.assertTrue(
            any("new=[{" in error and "stale=[]" in error for error in errors)
        )
        manifest["compatibility_consumers"] = boundaries._literal_consumers(
            root, {symbol}
        )
        self.assertEqual(boundaries.compatibility_errors(root, manifest), [])
        (root / "app" / "consumer.py").write_text("", encoding="utf-8")
        self.assertTrue(
            any(
                "new=[]" in error and "stale=[{" in error
                for error in boundaries.compatibility_errors(root, manifest)
            )
        )

    def test_patch_aliases_concrete_symbol_and_no_unrelated_patch(self):
        root = self._project()
        (root / "app" / "consumer.py").write_text(
            "import app.agent_runtime.service\n"
            "from unittest.mock import patch as change\n"
            "import unrelated as other\n"
            "change.object(app.agent_runtime.service, '_run_agent_impl')\n"
            "change.dict(app.agent_runtime.service.TOOL_HANDLERS, {})\n"
            "other.patch('app.agent_runtime.service.emit')\n",
            encoding="utf-8",
        )
        symbol = "app.agent_runtime.service"
        found = boundaries._literal_consumers(
            root, {symbol, symbol + "._run_agent_impl"}
        )
        self.assertIn(
            {
                "file": "app/consumer.py",
                "symbol": symbol + "._run_agent_impl",
                "kind": "patch.object",
            },
            found,
        )
        self.assertIn(
            {"file": "app/consumer.py", "symbol": symbol, "kind": "patch.dict"}, found
        )
        self.assertFalse(any(item["kind"] == "patch" for item in found))

    def test_package_relative_import(self):
        root = self._project()
        (root / "app" / "agent_runtime").mkdir()
        (root / "app" / "agent_runtime" / "__init__.py").write_text(
            "from . import service\n", encoding="utf-8"
        )
        found = boundaries._literal_consumers(root, {"app.agent_runtime.service"})
        self.assertEqual(
            found,
            [
                {
                    "file": "app/agent_runtime/__init__.py",
                    "symbol": "app.agent_runtime.service",
                    "kind": "import",
                }
            ],
        )

    def test_database_initializer_and_sql_keywords(self):
        root = self._project()
        (root / "app" / "consumer.py").write_text(
            "deps.ensure_department_databases()\ndeps.seed_reference_data()\n"
            "connection.execute('CREATE TABLE IF NOT EXISTS lots(x); "
            "INSERT INTO lots VALUES(1) ON CONFLICT DO UPDATE SET x=1')\n",
            encoding="utf-8",
        )
        candidate = boundaries.database_candidates(root)[0]
        self.assertEqual(candidate["table_hints"], ["lots"])
        self.assertIn("deps.seed_reference_data", candidate["calls"])

    def test_cli_malformed_input_writes_failure_report(self):
        root = self._project()
        manifest_path, report = root / "manifest.json", root / "report.json"
        bad = self._manifest(root)
        bad["allowed_dependencies"]["runtime"] = [{}]
        manifest_path.write_text(json.dumps(bad), encoding="utf-8")
        with mock.patch.object(boundaries, "PROJECT_DIR", root):
            self.assertEqual(
                boundaries.main(
                    ["--manifest", str(manifest_path), "--report", str(report)]
                ),
                1,
            )
        result = json.loads(report.read_text())
        self.assertFalse(result["ok"])
        self.assertIn("allowed_dependencies", result["errors"][0])

    def test_fresh_process_checker_does_not_import_app(self):
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from scripts import check_modularization_boundaries as b; "
            "assert b.validate(b.PROJECT_DIR,b.load_manifest()) == []; "
            "assert not any(x == 'app' or x.startswith('app.') for x in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code, str(boundaries.PROJECT_DIR)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
