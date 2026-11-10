from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.skills.catalog import CatalogEntry, SkillCatalog, SkillReference
from app.skills.contracts import DependencyInventory, SkillPackageError
from app.skills.discovery import DiscoveryQuery, discover

ROOT = Path("evaluations/skills/catalog_discovery_v1")
INVENTORY = DependencyInventory(
    {"get_equipment_health": "1.0.0"},
    {"fixture-workflow": "1.0.0"},
    {"fixture-evidence-policy": "1.0.0"},
)


def package(root: Path, *, version: str = "1.0.0", status: str = "published") -> None:
    root.mkdir(parents=True)
    data = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    data["version"] = version
    data["status"] = status
    (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    (root / "SKILL.md").write_text("instructions", encoding="utf-8")
    (root / "references").mkdir()
    (root / "references" / "catalog.md").write_text("reference", encoding="utf-8")
    (root / "scenarios").mkdir()
    (root / "scenarios" / "catalog.json").write_text("{}", encoding="utf-8")


class SkillCatalogTests(unittest.TestCase):
    def test_catalog_is_sorted_and_does_not_read_declared_resources(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            a, b = root / "a", root / "b"
            package(a, version="2.0.0")
            package(b, version="1.0.0")
            catalog = SkillCatalog.build((a, b), INVENTORY)
            self.assertEqual(
                [item.reference.version for item in catalog.entries], ["1.0.0", "2.0.0"]
            )
            self.assertTrue(all(item.available for item in catalog.entries))
            with self.assertRaises(SkillPackageError) as error:
                SkillCatalog.build((a, a), INVENTORY)
            self.assertEqual(error.exception.code, "duplicate_skill")

    def test_catalog_reads_only_manifest_and_keeps_multiple_versions(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            low, high = root / "low", root / "high"
            package(low, version="1.2.0")
            package(high, version="1.10.0")
            for item in (low / "SKILL.md", high / "SKILL.md"):
                item.unlink()
            with mock.patch(
                "app.skills.manifest.read_resource_text",
                wraps=__import__(
                    "app.skills.manifest", fromlist=["read_resource_text"]
                ).read_resource_text,
            ) as read:
                catalog = SkillCatalog.build((high, low), INVENTORY)
            self.assertEqual(
                [call.args[1] for call in read.call_args_list],
                ["manifest.json", "manifest.json"],
            )
            result = discover(
                catalog,
                DiscoveryQuery(
                    "fixture-workflow", "LITHO", "ready", frozenset({"lot_id"})
                ),
            )
            self.assertEqual(
                [entry.reference.version for entry in result.candidates],
                ["1.2.0", "1.10.0"],
            )

    def test_unavailable_entries_and_discovery_constraints_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            published, disabled = root / "published", root / "disabled"
            package(published)
            package(disabled, version="1.0.1", status="disabled")
            catalog = SkillCatalog.build((disabled, published), INVENTORY)
            result = discover(
                catalog,
                DiscoveryQuery(
                    "fixture-workflow", "LITHO", "ready", frozenset({"lot_id"})
                ),
            )
            self.assertEqual(
                [entry.reference.version for entry in result.candidates], ["1.0.0"]
            )
            self.assertEqual(result.rejections[0].reason, "ineligible_status")
            for query, expected in (
                (
                    DiscoveryQuery("other", "LITHO", "ready", frozenset({"lot_id"})),
                    "workflow_mismatch",
                ),
                (
                    DiscoveryQuery(
                        "fixture-workflow", "CMP", "ready", frozenset({"lot_id"})
                    ),
                    "process_step_mismatch",
                ),
                (
                    DiscoveryQuery("fixture-workflow", "LITHO", "ready", frozenset()),
                    "missing_required_input",
                ),
            ):
                self.assertEqual(
                    discover(SkillCatalog.build((published,), INVENTORY), query)
                    .rejections[0]
                    .reason,
                    expected,
                )

    def test_dependency_unavailability_unknown_reference_and_cwd_stability(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            package(root / "item")
            relative = os.path.relpath(root / "item")
            catalog = SkillCatalog.build((relative,), DependencyInventory({}, {}, {}))
            self.assertEqual(
                catalog.entries[0].unavailable_reason, "missing_dependency"
            )
            previous = Path.cwd()
            try:
                os.chdir(Path(temporary))
                self.assertTrue(catalog.entries[0].root.is_absolute())
            finally:
                os.chdir(previous)
            with self.assertRaises(SkillPackageError) as error:
                catalog.find(SkillReference("catalog-validation", "9.0.0"))
            self.assertEqual(error.exception.code, "unknown_skill")

    def test_catalog_constructor_and_incompatible_dependencies_fail_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary) / "item"
            package(root)
            catalog = SkillCatalog.build((root,), INVENTORY)
            with self.assertRaises(SkillPackageError):
                SkillCatalog(catalog.inventory, list(catalog.entries))  # type: ignore[arg-type]
            with self.assertRaises(SkillPackageError):
                CatalogEntry(
                    SkillReference("different-skill", "1.0.0"),
                    catalog.entries[0].root,
                    catalog.entries[0].manifest,
                )
            incompatible = DependencyInventory(
                {"get_equipment_health": "2.0.0"},
                {"fixture-workflow": "1.0.0"},
                {"fixture-evidence-policy": "1.0.0"},
            )
            unavailable = SkillCatalog.build((root,), incompatible)
            self.assertEqual(
                unavailable.entries[0].unavailable_reason, "incompatible_dependency"
            )

    def test_invalid_query_shapes_fail_closed(self) -> None:
        for query in (
            lambda: DiscoveryQuery(execution_mode="bad"),
            lambda: DiscoveryQuery(execution_mode=[]),  # type: ignore[arg-type]
            lambda: DiscoveryQuery(execution_mode={}),  # type: ignore[arg-type]
            lambda: DiscoveryQuery(execution_mode=False),  # type: ignore[arg-type]
            lambda: DiscoveryQuery(workflow_id=[]),  # type: ignore[arg-type]
            lambda: DiscoveryQuery(process_step={}),  # type: ignore[arg-type]
            lambda: DiscoveryQuery(available_inputs={"lot_id"}),  # type: ignore[arg-type]
            lambda: DiscoveryQuery(available_inputs=frozenset({1})),  # type: ignore[arg-type]
        ):
            with self.assertRaises(SkillPackageError):
                query()


if __name__ == "__main__":
    unittest.main()
