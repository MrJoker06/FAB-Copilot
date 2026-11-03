from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.skills.catalog import SkillCatalog, SkillReference
from app.skills.contracts import DependencyInventory, SkillPackageError
from app.skills.loader import SkillLoader

ROOT = Path("evaluations/skills/catalog_discovery_v1")
INVENTORY = DependencyInventory(
    {"get_equipment_health": "1.0.0"},
    {"fixture-workflow": "1.0.0"},
    {"fixture-evidence-policy": "1.0.0"},
)


def copy_package(root: Path) -> None:
    import shutil

    shutil.copytree(ROOT, root)


class SkillLoaderTests(unittest.TestCase):
    def test_load_then_expand_is_incremental_immutable_and_idempotent(self) -> None:
        catalog = SkillCatalog.build((ROOT,), INVENTORY)
        loader = SkillLoader(catalog)
        reference = SkillReference("catalog-validation", "1.0.0")
        snapshot = loader.load(reference)
        self.assertEqual(
            [item.path for item in snapshot.loaded_resources], ["SKILL.md"]
        )
        expanded = loader.expand(snapshot, ("references/catalog.md",))
        self.assertEqual(
            [item.path for item in expanded.loaded_resources],
            ["SKILL.md", "references/catalog.md"],
        )
        self.assertEqual(len(snapshot.loaded_resources), 1)
        again = loader.expand(expanded, ("references/catalog.md",))
        self.assertEqual(again.loaded_resources, expanded.loaded_resources)
        self.assertFalse(again.execution_authorized)

    def test_loader_rejects_exact_missing_undeclared_and_stale_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            copy_package(root)
            catalog = SkillCatalog.build((root,), INVENTORY)
            loader = SkillLoader(catalog)
            with self.assertRaises(SkillPackageError) as error:
                loader.load(SkillReference("catalog-validation", "9.0.0"))
            self.assertEqual(error.exception.code, "unknown_skill")
            snap = loader.load(SkillReference("catalog-validation", "1.0.0"))
            with self.assertRaises(SkillPackageError) as error:
                loader.expand(snap, ("not-declared.md",))
            self.assertEqual(error.exception.code, "undeclared_resource")
            data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            data["workflow"]["component_id"] = "changed-workflow"
            (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SkillPackageError) as error:
                loader.expand(snap, ("references/catalog.md",))
            self.assertEqual(error.exception.code, "stale_catalog")
            data["workflow"]["component_id"] = "fixture-workflow"
            data["status"] = "disabled"
            (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SkillPackageError) as error:
                loader.expand(snap, ())
            self.assertEqual(error.exception.code, "stale_catalog")

    def test_resource_opening_happens_after_selection_only(self) -> None:
        catalog = SkillCatalog.build((ROOT,), INVENTORY)
        loader = SkillLoader(catalog)
        with mock.patch(
            "app.skills.loader.read_resource_text",
            wraps=__import__(
                "app.skills.loader", fromlist=["read_resource_text"]
            ).read_resource_text,
        ) as read:
            loader.load(SkillReference("catalog-validation", "1.0.0"))
            self.assertEqual(read.call_count, 1)
            loader.expand(
                loader.load(SkillReference("catalog-validation", "1.0.0")),
                ("references/catalog.md",),
            )
            self.assertGreaterEqual(read.call_count, 3)

    def test_unavailable_loader_and_ready_only_mismatch_do_not_open_bodies(
        self,
    ) -> None:
        from app.skills.discovery import DiscoveryQuery, discover

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            copy_package(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            manifest["execution_modes"] = ["ready"]
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            catalog = SkillCatalog.build((root,), INVENTORY)
            result = discover(
                catalog,
                DiscoveryQuery(
                    "fixture-workflow", "LITHO", "loop", frozenset({"lot_id"})
                ),
            )
            self.assertEqual(result.rejections[0].reason, "execution_mode_mismatch")
            manifest["status"] = "disabled"
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            catalog = SkillCatalog.build((root,), INVENTORY)
            with (
                mock.patch("app.skills.loader.read_resource_text") as read,
                self.assertRaises(SkillPackageError) as error,
            ):
                SkillLoader(catalog).load(SkillReference("catalog-validation", "1.0.0"))
            self.assertEqual(error.exception.code, "ineligible_status")
            read.assert_not_called()

    def test_snapshot_loader_identity_and_manifest_content_stay_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            copy_package(root)
            catalog = SkillCatalog.build((root,), INVENTORY)
            first = SkillLoader(catalog)
            snap = first.load(SkillReference("catalog-validation", "1.0.0"))
            (root / "SKILL.md").write_text("changed", encoding="utf-8")
            self.assertIn("declarative", snap.loaded_resources[0].text)
            with self.assertRaises(SkillPackageError):
                SkillLoader(catalog).expand(snap, ())

    def test_incremental_aggregate_budget_is_exact_and_fails_before_extra_read(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "package"
            copy_package(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            manifest["resources"] = [{"path": "SKILL.md", "kind": "instructions"}]
            paths = []
            for number in range(4):
                path = f"references/{number}.txt"
                manifest["resources"].append({"path": path, "kind": "reference"})
                (root / "references" / f"{number}.txt").write_bytes(b"x" * (256 * 1024))
                paths.append(path)
            manifest["resources"].append(
                {"path": "references/overflow.txt", "kind": "reference"}
            )
            (root / "references" / "overflow.txt").write_text("x", encoding="utf-8")
            (root / "SKILL.md").write_bytes(b"")
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            loader = SkillLoader(SkillCatalog.build((root,), INVENTORY))
            snapshot = loader.load(SkillReference("catalog-validation", "1.0.0"))
            exact = loader.expand(snapshot, tuple(paths))
            self.assertEqual(
                sum(len(item.text.encode("utf-8")) for item in exact.loaded_resources),
                1024 * 1024,
            )
            with self.assertRaises(SkillPackageError) as error:
                loader.expand(exact, ("references/overflow.txt",))
            self.assertEqual(error.exception.code, "resource_budget")


if __name__ == "__main__":
    unittest.main()
