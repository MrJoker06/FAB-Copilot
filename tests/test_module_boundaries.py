from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_module_boundaries import (
    boundary_errors,
    consumer_inventory,
    imported_modules,
    load_manifest,
)


class ModuleBoundaryTests(unittest.TestCase):
    def write_app(self, root: Path, files: dict[str, str]) -> Path:
        app = root / "app"
        app.mkdir()
        for name, content in files.items():
            path = app / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return app

    def manifest(self, root: Path, roots: list[str], *, pure: list[str] | None = None) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": 1,
            "policy": {
                "forbidden_targets": ["app.main", "app.agent", "app.agent_runtime.coordinator"],
                "pure_modules": pure or [],
                "pure_forbidden_targets": ["app.database", "app.main", "app.agent"],
            },
            "existing_edge_exceptions": [],
            "package_ownership": {"target": "app", "compatibility": "retain", "exit_condition": "never", "consumers": {"production": [], "scripts": [], "tests": ["test"], "patches": []}},
            "canonical_modules": {f"app.{name}": name for name in roots},
            "allowed_domain_dependencies": {name: list(roots) for name in roots},
            "root_modules": {
                name: {"target": name, "compatibility": "retain", "exit_condition": "test", "consumers": {"production": [], "scripts": [], "tests": ["test"], "patches": []}}
                for name in roots
            },
        }
        path = root / "manifest.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return load_manifest(path)

    def test_rejects_domain_backedge_and_missing_root_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {"main.py": "", "domain.py": "import app.main\n", "orphan.py": ""})
            errors = boundary_errors(app, self.manifest(root, ["main", "domain"]))
        self.assertIn("root ownership missing: orphan", errors)
        self.assertIn("app.domain:1: domain module imports forbidden app.main", errors)

    def test_rejects_pure_database_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {"__init__.py": "", "database.py": "", "rules.py": "from app import database\n"})
            manifest = self.manifest(root, ["database", "rules"], pure=["app.rules"])
            errors = boundary_errors(app, manifest)
        self.assertEqual(errors, ["app.rules:1: pure module imports forbidden app.database"])

    def test_rejects_malformed_and_stale_exceptions_without_crashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {"__init__.py": "", "database.py": "", "rules.py": ""})
            manifest = self.manifest(root, ["database", "rules"])
            manifest["existing_edge_exceptions"] = [
                "not an exception",
                {"source": "app.rules", "target": "app.database", "reason": "test", "exit_condition": "REF-999"},
            ]
            errors = boundary_errors(app, manifest)
        self.assertEqual(errors, [
            "edge exception must contain exact source, target, reason and exit_condition fields",
            "stale edge exception: app.rules -> app.database",
        ])

    def test_accepts_only_the_exact_existing_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {
                "__init__.py": "", "main.py": "", "agent.py": "",
                "domain.py": "import app.main\nimport app.agent\n",
            })
            manifest = self.manifest(root, ["main", "agent", "domain"])
            manifest["existing_edge_exceptions"] = [{
                "source": "app.domain", "target": "app.main", "reason": "compatibility", "exit_condition": "REF-999",
            }]
            errors = boundary_errors(app, manifest)
        self.assertEqual(errors, ["app.domain:2: domain module imports forbidden app.agent"])

    def test_rejects_cross_domain_dependency_and_malformed_dependency_mappings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {"__init__.py": "", "source.py": "import app.target\n", "target.py": ""})
            manifest = self.manifest(root, ["source", "target"])
            manifest["allowed_domain_dependencies"] = {"source": ["source"], "target": ["target"]}
            errors = boundary_errors(app, manifest)
            manifest["allowed_domain_dependencies"] = {"source": "invalid"}
            malformed_allowed_errors = boundary_errors(app, manifest)
            manifest["allowed_domain_dependencies"] = {"target": ["target"]}
            missing_source_policy_errors = boundary_errors(app, manifest)
            manifest["canonical_modules"] = ["invalid"]
            malformed_canonical_errors = boundary_errors(app, manifest)
        self.assertEqual(errors, ["app.source:1: source may not depend on target"])
        self.assertIn("allowed domain dependencies must map non-empty domains to string lists", malformed_allowed_errors)
        self.assertIn("allowed domain dependencies missing policy for: source", missing_source_policy_errors)
        self.assertIn("canonical module mapping must be an object", malformed_canonical_errors)

    def test_requires_all_consumer_path_buckets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {"__init__.py": "", "rules.py": ""})
            manifest = self.manifest(root, ["rules"])
            manifest["root_modules"]["rules"]["consumers"] = {"tests": ["test"]}
            errors = boundary_errors(app, manifest)
        self.assertIn("root ownership incomplete: rules", errors)

    def test_rejects_pure_network_and_runtime_tool_backedges(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {
                "__init__.py": "", "agent.py": "", "database.py": "", "pure.py": "import socket\n",
                "agent_runtime/__init__.py": "", "agent_runtime/coordinator.py": "", "agent_runtime/tools.py": "from .. import agent\n",
            })
            manifest = self.manifest(root, ["agent", "database", "pure"], pure=["app.pure"])
            manifest["policy"]["pure_forbidden_prefixes"] = ["socket"]
            manifest["policy"]["assembly_modules"] = []
            errors = boundary_errors(app, manifest)
        self.assertIn("app.pure:1: pure module imports forbidden socket", errors)
        self.assertIn("app.agent_runtime.tools:1: domain module imports forbidden app.agent", errors)

    def test_finds_relative_package_and_literal_dynamic_import_forms(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {
                "__init__.py": "", "main.py": "", "agent.py": "", "domain.py": (
                    "from . import main\nfrom app import agent\nimport importlib as loader\n"
                    "from importlib import import_module as load\nloader.import_module('app.main')\nload('app.agent')\n"
                ),
            })
            edges = imported_modules(app / "domain.py", app)
        self.assertEqual(
            {(edge.target, edge.line) for edge in edges},
            {("app", 1), ("app.main", 1), ("app", 2), ("app.agent", 2), ("importlib", 3), ("importlib", 4), ("app.main", 5), ("app.agent", 6)},
        )

    def test_inventory_reports_real_import_and_patch_consumers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_app(root, {"__init__.py": "", "agent.py": "", "main.py": "", "worker.py": "from . import agent\n"})
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_example.py").write_text("from app import agent\npatch('app.main.run')\n", encoding="utf-8")
            inventory = consumer_inventory(root)
        self.assertEqual(inventory["agent"]["tests"], ["tests/test_example.py"])
        self.assertEqual(inventory["agent"]["production"], ["app/worker.py"])
        self.assertEqual(inventory["main"]["patches"], ["tests/test_example.py"])

    def test_real_manifest_rejects_nested_pure_network_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_app = Path(temporary) / "app"
            shutil.copytree(Path(__file__).resolve().parents[1] / "app", copied_app)
            target = copied_app / "assistant_capabilities.py"
            target.write_text(target.read_text(encoding="utf-8") + "\nfrom socket import socket\n", encoding="utf-8")
            errors = boundary_errors(copied_app, load_manifest())
        self.assertTrue(any("pure module imports forbidden socket" in error for error in errors))

    def test_real_manifest_rejects_tool_to_coordinator_from_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_app = Path(temporary) / "app"
            shutil.copytree(Path(__file__).resolve().parents[1] / "app", copied_app)
            target = copied_app / "agent_runtime" / "tools" / "registry.py"
            target.write_text(target.read_text(encoding="utf-8") + "\nfrom app.agent_runtime import coordinator\n", encoding="utf-8")
            errors = boundary_errors(copied_app, load_manifest())
        self.assertTrue(any("domain module imports forbidden app.agent_runtime.coordinator" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
