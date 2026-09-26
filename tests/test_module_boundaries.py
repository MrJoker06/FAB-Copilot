from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.check_module_boundaries import (
    boundary_errors,
    consumer_inventory,
    facade_inventory_errors,
    imported_modules,
    load_manifest,
    retired_module_errors,
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
                "forbidden_targets": ["app.main", "app.agent_runtime.service", "app.agent_runtime.coordinator"],
                "pure_modules": pure or [],
                "pure_forbidden_targets": ["app.persistence.database", "app.main", "app.agent_runtime.service"],
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
            app = self.write_app(root, {"__init__.py": "", "persistence/database.py": "", "rules.py": "from app.persistence import database\n"})
            manifest = self.manifest(root, ["rules"], pure=["app.rules"])
            manifest["canonical_modules"]["app.persistence.database"] = "persistence.database"
            manifest["allowed_domain_dependencies"]["persistence"] = ["persistence"]
            manifest["allowed_domain_dependencies"]["rules"].append("persistence")
            errors = boundary_errors(app, manifest)
        self.assertEqual(errors, ["app.rules:1: pure module imports forbidden app.persistence.database"])

    def test_rejects_malformed_and_stale_exceptions_without_crashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {"__init__.py": "", "database.py": "", "rules.py": ""})
            manifest = self.manifest(root, ["database", "rules"])
            manifest["existing_edge_exceptions"] = [
                "not an exception",
                {"source": "app.rules", "target": "app.persistence.database", "reason": "test", "exit_condition": "REF-999"},
            ]
            errors = boundary_errors(app, manifest)
        self.assertEqual(errors, [
            "edge exception must contain exact source, target, reason and exit_condition fields",
            "stale edge exception: app.rules -> app.persistence.database",
        ])

    def test_accepts_only_the_exact_existing_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {
                "__init__.py": "", "main.py": "", "agent.py": "",
                "domain.py": "import app.main\nimport app.agent_runtime.service\n",
            })
            manifest = self.manifest(root, ["main", "agent", "domain"])
            manifest["existing_edge_exceptions"] = [{
                "source": "app.domain", "target": "app.main", "reason": "compatibility", "exit_condition": "REF-999",
            }]
            errors = boundary_errors(app, manifest)
        self.assertEqual(errors, ["app.domain:2: domain module imports forbidden app.agent_runtime.service"])

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
                "agent_runtime/__init__.py": "", "agent_runtime/service.py": "", "agent_runtime/coordinator.py": "", "agent_runtime/tools.py": "from . import service\n",
            })
            manifest = self.manifest(root, ["agent", "database", "pure"], pure=["app.pure"])
            manifest["canonical_modules"]["app.agent_runtime.service"] = "agent_runtime.service"
            manifest["allowed_domain_dependencies"]["agent_runtime"] = ["agent_runtime"]
            manifest["policy"]["pure_forbidden_prefixes"] = ["socket"]
            manifest["policy"]["assembly_modules"] = []
            errors = boundary_errors(app, manifest)
        self.assertIn("app.pure:1: pure module imports forbidden socket", errors)
        self.assertIn("app.agent_runtime.tools:1: domain module imports forbidden app.agent_runtime.service", errors)

    def test_finds_relative_package_and_literal_dynamic_import_forms(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {
                "__init__.py": "", "main.py": "", "agent.py": "", "domain.py": (
                    "from . import main\nfrom app.agent_runtime import service as agent\nimport importlib as loader\n"
                    "from importlib import import_module as load\nloader.import_module('app.main')\nload('app.agent_runtime.service')\n"
                ),
            })
            edges = imported_modules(app / "domain.py", app)
        self.assertEqual(
            {(edge.target, edge.line) for edge in edges},
            {("app", 1), ("app.main", 1), ("app.agent_runtime", 2), ("importlib", 3), ("importlib", 4), ("app.main", 5), ("app.agent_runtime.service", 6)},
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

    def test_retirement_policy_rejects_old_imports_and_root_reintroduction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {"__init__.py": "", "main.py": "", "knowledge/rag.py": ""})
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "consumer.py").write_text("from app import rag\n", encoding="utf-8")
            manifest = self.manifest(root, ["main"])
            manifest["retired_modules"] = {"app.rag": {"target": "app.knowledge.rag", "reason": "REF-035"}}
            self.assertEqual(retired_module_errors(root, manifest), ["scripts/consumer.py:1: imports retired module app.rag"])
            (app / "rag.py").write_text("", encoding="utf-8")
            self.assertIn("retired root module reintroduced: app.rag", retired_module_errors(root, manifest))

    def test_retirement_policy_detects_relative_nested_and_dynamic_imports_without_old_file(self):
        cases = {
            "app/worker.py": "from . import rag\n",
            "app/nested/worker.py": "from .. import rag\n",
            "scripts/direct.py": "import app.rag\n",
            "scripts/dynamic.py": "import importlib as loader\nloader.import_module('app.rag')\n",
            "tests/test_dynamic.py": "from importlib import import_module\nimport_module('.rag', package='app')\n",
        }
        for relative, content in cases.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_app(root, {"__init__.py": "", "main.py": "", "knowledge/rag.py": ""})
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                manifest = self.manifest(root, ["main"])
                manifest["retired_modules"] = {"app.rag": {"target": "app.knowledge.rag", "reason": "REF-035"}}
                self.assertEqual(retired_module_errors(root, manifest), [f"{relative}:2: imports retired module app.rag"] if "dynamic" in relative else [f"{relative}:1: imports retired module app.rag"])

    def test_retirement_policy_accepts_canonical_import_and_frozen_display_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_app(root, {"__init__.py": "", "main.py": "", "knowledge/rag.py": ""})
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "canonical.py").write_text("import app.knowledge.rag\nLABEL = 'MODULE:app.rag'\n", encoding="utf-8")
            manifest = self.manifest(root, ["main"])
            manifest["retired_modules"] = {"app.rag": {"target": "app.knowledge.rag", "reason": "REF-035"}}
            self.assertEqual(retired_module_errors(root, manifest), [])

    def test_retirement_policy_rejects_invalid_schema_and_missing_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_app(root, {"__init__.py": "", "main.py": "", "knowledge/rag.py": ""})
            manifest = self.manifest(root, ["main"])
            manifest["retired_modules"] = {
                "app.rag.child": {"target": "app.knowledge.rag", "reason": "REF-035"},
                "app.bad": {"target": "app.missing", "reason": "REF-035"},
                "app.schema": {"target": "app.knowledge.rag"},
                3: {},
            }
            errors = retired_module_errors(root, manifest)
            self.assertIn("retired module mapping must use app module keys and objects", errors)
            self.assertIn("retired module target missing: app.bad -> app.missing", errors)
            self.assertIn("retired module mapping incomplete: app.schema", errors)

    def test_retirement_policy_rejects_old_prefix_and_positional_dynamic_aliases(self):
        cases = {
            "scripts/prefix.py": "import app.rag.child\n",
            "scripts/alias.py": "from importlib import import_module as load\nload('.rag', 'app')\n",
            "scripts/helper.py": "def load_old():\n    from importlib import import_module as load\n    return load('.rag', 'app')\n",
        }
        for relative, content in cases.items():
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_app(root, {"__init__.py": "", "main.py": "", "knowledge/rag.py": ""})
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                manifest = self.manifest(root, ["main"])
                manifest["retired_modules"] = {"app.rag": {"target": "app.knowledge.rag", "reason": "REF-035"}}
                expected_line = 1 if relative.endswith("prefix.py") else (2 if relative.endswith("alias.py") else 3)
                self.assertEqual(retired_module_errors(root, manifest), [f"{relative}:{expected_line}: imports retired module app.rag" if not relative.endswith("prefix.py") else f"{relative}:1: imports retired module app.rag.child"])

    def test_internal_facade_policy_rejects_each_import_form_and_ignores_fixture_strings(self):
        cases = (
            ("production", "app/worker.py", "from . import legacy\n"),
            ("scripts", "scripts/audit.py", "from app import legacy, missing\n"),
            ("scripts", "scripts/dynamic.py", "from importlib import import_module as load\nload('.legacy', 'app')\n"),
            ("scripts", "scripts/keyword.py", "import importlib as loader\nloader.import_module('.legacy', package='app')\n"),
            ("production", "app/worker.py", "def load():\n    from importlib import import_module as loader\n    return loader('.legacy', 'app')\n"),
            ("scripts", "scripts/function_dynamic.py", "def load():\n    from importlib import import_module as loader\n    return loader('.legacy', package='app')\n"),
            ("tests", "tests/test_dynamic.py", "from importlib import import_module\nimport_module('app.legacy')\n"),
        )
        for bucket, relative, content in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_app(root, {"__init__.py": "", "legacy.py": "", "worker.py": ""})
                target = root / relative
                target.parent.mkdir(exist_ok=True)
                target.write_text(content, encoding="utf-8")
                manifest = self.manifest(root, ["legacy", "worker"])
                manifest["policy"]["internal_facades"] = ["legacy"]
                manifest["root_modules"]["legacy"]["consumers"] = {"production": [], "scripts": [], "tests": [], "patches": []}
                inventory = consumer_inventory(root)
                errors = facade_inventory_errors(root, manifest)
                self.assertEqual(inventory["legacy"][bucket], [relative])
                if bucket in {"production", "scripts"}:
                    self.assertEqual(errors, ["internal facade has production or script consumers: legacy", "internal facade consumer inventory stale: legacy"])
                else:
                    self.assertEqual(errors, ["internal facade consumer inventory stale: legacy"])

                if relative == "app/worker.py" and "import_module" in content:
                    manifest["root_modules"]["legacy"]["consumers"]["production"] = [relative]
                    self.assertEqual(
                        facade_inventory_errors(root, manifest),
                        ["internal facade has production or script consumers: legacy"],
                    )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_app(root, {"__init__.py": "", "legacy.py": ""})
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_fixture.py").write_text('FIXTURE = "from app import legacy"\n', encoding="utf-8")
            manifest = self.manifest(root, ["legacy"])
            manifest["policy"]["internal_facades"] = ["legacy"]
            manifest["root_modules"]["legacy"]["consumers"] = {"production": [], "scripts": [], "tests": [], "patches": []}
            self.assertEqual(consumer_inventory(root)["legacy"]["tests"], [])
            self.assertEqual(facade_inventory_errors(root, manifest), [])

    def test_internal_facade_policy_rejects_malformed_and_missing_roots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_app(root, {"__init__.py": "", "legacy.py": ""})
            manifest = self.manifest(root, ["legacy"])
            manifest["policy"]["internal_facades"] = "legacy"
            malformed = facade_inventory_errors(root, manifest)
            manifest["policy"]["internal_facades"] = ["missing"]
            missing = facade_inventory_errors(root, manifest)
        self.assertEqual(malformed, ["internal facade policy must be a list of non-empty root names"])
        self.assertEqual(missing, ["internal facade policy missing root ownership: missing"])

    def test_synthetic_policy_rejects_prior_facade_reintroduction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_app(root, {"__init__.py": "", "rag.py": "", "compat.py": ""})
            manifest = self.manifest(root, ["rag", "compat"])
            manifest["policy"]["internal_facades"] = ["rag"]
            manifest["root_modules"]["rag"]["consumers"] = {"production": [], "scripts": [], "tests": [], "patches": []}
            self.assertEqual(facade_inventory_errors(root, manifest), [])
            target = root / "app" / "compat.py"
            target.write_text("from app import rag\n", encoding="utf-8")
            self.assertEqual(consumer_inventory(root)["rag"]["production"], ["app/compat.py"])
            self.assertEqual(
                facade_inventory_errors(root, manifest),
                ["internal facade has production or script consumers: rag", "internal facade consumer inventory stale: rag"],
            )

    def test_same_stem_nested_canonical_module_is_a_facade_consumer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_app(root, {
                "__init__.py": "", "rag.py": "", "knowledge/__init__.py": "",
                "knowledge/rag.py": "from app import rag\n",
            })
            manifest = self.manifest(root, ["rag"])
            manifest["policy"]["internal_facades"] = ["rag"]
            manifest["root_modules"]["rag"]["consumers"] = {"production": [], "scripts": [], "tests": [], "patches": []}
            self.assertEqual(consumer_inventory(root)["rag"]["production"], ["app/knowledge/rag.py"])
            self.assertEqual(
                facade_inventory_errors(root, manifest),
                ["internal facade has production or script consumers: rag", "internal facade consumer inventory stale: rag"],
            )

    def test_real_manifest_rejects_nested_pure_network_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_app = Path(temporary) / "app"
            shutil.copytree(Path(__file__).resolve().parents[1] / "app", copied_app)
            target = copied_app / "agent_runtime" / "assistant_capabilities.py"
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

    def test_real_manifest_rejects_pure_manufacturing_processes_database_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_app = Path(temporary) / "app"
            shutil.copytree(Path(__file__).resolve().parents[1] / "app", copied_app)
            target = copied_app / "manufacturing" / "processes.py"
            target.write_text(target.read_text(encoding="utf-8") + "\nfrom app.persistence import database\n", encoding="utf-8")
            errors = boundary_errors(copied_app, load_manifest())
        self.assertTrue(any("app.manufacturing.processes" in error and "pure module imports forbidden app.persistence.database" in error for error in errors))

    def test_memory_domain_policy_rejects_absolute_relative_dynamic_and_runtime_imports(self):
        cases = {
            "absolute.py": "from app.api import services\n",
            "relative.py": "from ..api import services\n",
            "dynamic.py": "import importlib\nimportlib.import_module('app.persistence.database')\n",
            "runtime.py": "import socket\n",
        }
        for name, content in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app = self.write_app(root, {
                    "__init__.py": "", "main.py": "", "memory_system/__init__.py": "",
                    f"memory_system/{name}": content, "api/__init__.py": "", "api/services.py": "",
                    "persistence/__init__.py": "", "persistence/database.py": "",
                })
                manifest = self.manifest(root, ["main"])
                manifest["canonical_modules"].update({
                    "app.memory_system": "memory_system",
                    "app.api": "api",
                    "app.persistence": "persistence",
                })
                manifest["allowed_domain_dependencies"].update({
                    "memory_system": ["memory_system"], "api": ["api"], "persistence": ["persistence"],
                })
                manifest["policy"]["domain_forbidden_imports"] = {
                    "memory_system": ["app.api", "app.persistence", "socket"],
                }
                errors = boundary_errors(app, manifest)
            self.assertTrue(errors)
            self.assertTrue(all("memory_system module imports forbidden" in error for error in errors), errors)

    def test_production_policy_rejects_conversation_facade_but_not_canonical_or_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = self.write_app(root, {
                "__init__.py": "", "main.py": "", "consumer.py": "from app.conversation import context_resolver\n",
                "canonical.py": "from app.memory_system import contracts\nLABEL = 'MODULE:app.conversation.context_resolver'\n",
                "conversation/__init__.py": "", "conversation/context_resolver.py": "",
                "memory_system/__init__.py": "", "memory_system/contracts.py": "",
            })
            manifest = self.manifest(root, ["main", "consumer", "canonical"])
            manifest["canonical_modules"].update({
                "app.conversation": "conversation", "app.memory_system": "memory_system",
            })
            manifest["allowed_domain_dependencies"].update({
                "conversation": ["conversation"], "memory_system": ["memory_system"],
            })
            manifest["allowed_domain_dependencies"]["canonical"].append("memory_system")
            manifest["allowed_domain_dependencies"]["consumer"].append("conversation")
            manifest["policy"]["production_forbidden_imports"] = ["app.conversation.context_resolver"]
            errors = boundary_errors(app, manifest)
        self.assertEqual(
            errors,
            ["app.consumer:1: production module imports forbidden compatibility facade app.conversation.context_resolver"],
        )


if __name__ == "__main__":
    unittest.main()
