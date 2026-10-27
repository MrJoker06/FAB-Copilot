from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts import build_portable_unit


class PortableUnitTests(unittest.TestCase):
    def setUp(self):
        self.manifest = build_portable_unit.load_manifest()

    def test_manifest_declares_the_initial_portable_units(self):
        self.assertEqual(
            set(self.manifest["units"]),
            {
                "memory_core",
                "decision_core",
                "model_transport",
                "enterprise_data_contract",
                "retrieval_policy",
                "factory_search_contract",
                "identity_contract",
            },
        )
        for name, definition in self.manifest["units"].items():
            files = build_portable_unit.validate_unit(name, definition)
            self.assertTrue(files)
            self.assertIn("app/__init__.py", definition["files"])

    def test_build_is_reproducible_and_contains_explicit_file_manifest(self):
        definition = self.manifest["units"]["memory_core"]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            first = build_portable_unit.build_unit("memory_core", definition, output)
            first_bytes = first.read_bytes()
            second = build_portable_unit.build_unit("memory_core", definition, output)
            self.assertEqual(first_bytes, second.read_bytes())
            with zipfile.ZipFile(second) as archive:
                metadata = json.loads(archive.read(build_portable_unit.ARCHIVE_MANIFEST))
                self.assertEqual(metadata["unit"], "memory_core")
                self.assertEqual(metadata["files"], definition["files"])
                self.assertEqual(set(metadata), {"schema_version", "unit", "version", "files"})

    def test_model_transport_records_only_its_external_requirement(self):
        definition = self.manifest["units"]["model_transport"]
        with tempfile.TemporaryDirectory() as temporary:
            bundle = build_portable_unit.build_unit(
                "model_transport", definition, Path(temporary)
            )
            with zipfile.ZipFile(bundle) as archive:
                metadata = json.loads(archive.read(build_portable_unit.ARCHIVE_MANIFEST))
        self.assertEqual(metadata["external_dependencies"], ["httpx>=0.28,<1"])
        self.assertEqual(set(archive.namelist()), {build_portable_unit.ARCHIVE_MANIFEST, *definition["files"]})

    def test_verify_rejects_undeclared_archive_members(self):
        definition = self.manifest["units"]["memory_core"]
        with tempfile.TemporaryDirectory() as temporary:
            bundle = build_portable_unit.build_unit("memory_core", definition, Path(temporary))
            with zipfile.ZipFile(bundle, "a") as archive:
                archive.writestr("extra.py", "raise RuntimeError('must not load')\n")
            with self.assertRaisesRegex(ValueError, "exactly match"):
                build_portable_unit.verify_bundle(bundle)

    def test_verify_runs_all_portable_unit_smoke_checks_outside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            for name, definition in self.manifest["units"].items():
                bundle = build_portable_unit.build_unit(name, definition, output)
                build_portable_unit.verify_bundle(bundle)

    def test_rejects_unsafe_paths_and_undeclared_app_imports(self):
        with self.assertRaisesRegex(ValueError, "unsafe portable unit path"):
            build_portable_unit.safe_relative_path("../data/fab_history.db")
        with self.assertRaisesRegex(ValueError, "unsafe portable unit path"):
            build_portable_unit.safe_relative_path("app\\escape.py")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app").mkdir()
            (root / "app/__init__.py").write_text("", encoding="utf-8")
            (root / "app/unit.py").write_text("import app.missing\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "undeclared app import app.missing"):
                build_portable_unit.validate_unit(
                    "unit",
                    {"version": "1", "files": ["app/__init__.py", "app/unit.py"]},
                    root,
                )

    def test_rejects_import_below_a_declared_package_when_module_is_not_declared(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app/foo").mkdir(parents=True)
            (root / "app/__init__.py").write_text("", encoding="utf-8")
            (root / "app/foo/__init__.py").write_text("", encoding="utf-8")
            (root / "app/unit.py").write_text("import app.foo.missing\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "undeclared app import app.foo.missing"):
                build_portable_unit.validate_unit(
                    "unit",
                    {
                        "version": "1",
                        "files": ["app/__init__.py", "app/foo/__init__.py", "app/unit.py"],
                    },
                    root,
                )

    def test_rejects_symlinked_declared_file_outside_project_root(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as external:
            root = Path(temporary)
            outside = Path(external) / "outside.py"
            outside.write_text("", encoding="utf-8")
            (root / "app").mkdir()
            (root / "app/__init__.py").write_text("", encoding="utf-8")
            (root / "app/leak.py").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "declared file escapes project root: app/leak.py"):
                build_portable_unit.validate_unit(
                    "unit",
                    {"version": "1", "files": ["app/__init__.py", "app/leak.py"]},
                    root,
                )

    def test_rejects_path_separators_and_traversal_in_archive_name_or_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.assertRaisesRegex(ValueError, "unsafe portable unit name"):
                build_portable_unit.build_unit(
                    "../memory_core", {"version": "1.0.0", "files": []}, output
                )
            with self.assertRaisesRegex(ValueError, "unsafe portable unit version"):
                build_portable_unit.build_unit(
                    "memory_core", {"version": "../outside", "files": []}, output
                )


if __name__ == "__main__":
    unittest.main()
