from __future__ import annotations

import unittest
from pathlib import Path

from app.skills.contracts import (
    DependencyInventory,
    ResourceDeclaration,
    SkillPackageError,
)
from app.skills.manifest import parse_manifest, validate_dependencies
from app.skills.versions import parse_version_requirement

FIXTURE = Path("evaluations/skills/manifest_validation_v1/manifest.json")


def inventory() -> DependencyInventory:
    return DependencyInventory(
        {"get_equipment_health": "1.0.0"},
        {"fixture-workflow": "1.0.0"},
        {"fixture-evidence-policy": "1.0.0"},
    )


class SkillManifestTests(unittest.TestCase):
    def test_fixture_manifest_is_immutable_and_dependency_checked(self) -> None:
        manifest = parse_manifest(FIXTURE.read_text(encoding="utf-8"))
        validate_dependencies(manifest, inventory())
        self.assertEqual(manifest.status, "published")
        with self.assertRaises((AttributeError, TypeError)):
            inventory().tools["new"] = "1.0.0"  # type: ignore[index]

    def test_rejects_duplicate_and_deep_json(self) -> None:
        for value in (
            '{"schema_version":"1.0.0","schema_version":"1.0.0"}',
            "[" * 1200 + "0" + "]" * 1200,
        ):
            with self.subTest(value=value[:20]), self.assertRaises(SkillPackageError):
                parse_manifest(value)

    def test_version_grammar_and_runtime_status(self) -> None:
        for requirement in ("1.0.0", "==1.0.0", ">=1.0.0,<2.0.0"):
            with self.subTest(requirement=requirement):
                self.assertTrue(parse_version_requirement(requirement).matches("1.0.0"))
        for requirement in ("^1.0.0", "1.0", "01.0.0", ">=2.0.0,<1.0.0"):
            with (
                self.subTest(requirement=requirement),
                self.assertRaises(SkillPackageError),
            ):
                parse_version_requirement(requirement)
        draft = parse_manifest(
            FIXTURE.read_text(encoding="utf-8").replace(
                '"status": "published"', '"status": "draft"'
            )
        )
        with self.assertRaises(SkillPackageError):
            validate_dependencies(draft, inventory())
        validate_dependencies(draft, inventory(), require_published=False)

    def test_direct_malformed_declarations_raise_public_errors(self) -> None:
        with self.assertRaises(SkillPackageError):
            ResourceDeclaration("SKILL.md", [])  # type: ignore[arg-type]

    def test_all_dependency_kinds_fail_closed_when_missing_or_wrong(self) -> None:
        manifest = parse_manifest(FIXTURE.read_text(encoding="utf-8"))
        inventories = (
            DependencyInventory(
                {}, {"fixture-workflow": "1.0.0"}, {"fixture-evidence-policy": "1.0.0"}
            ),
            DependencyInventory(
                {"get_equipment_health": "2.0.0"},
                {"fixture-workflow": "1.0.0"},
                {"fixture-evidence-policy": "1.0.0"},
            ),
            DependencyInventory(
                {"get_equipment_health": "1.0.0"},
                {},
                {"fixture-evidence-policy": "1.0.0"},
            ),
            DependencyInventory(
                {"get_equipment_health": "1.0.0"},
                {"fixture-workflow": "2.0.0"},
                {"fixture-evidence-policy": "1.0.0"},
            ),
            DependencyInventory(
                {"get_equipment_health": "1.0.0"}, {"fixture-workflow": "1.0.0"}, {}
            ),
            DependencyInventory(
                {"get_equipment_health": "1.0.0"},
                {"fixture-workflow": "1.0.0"},
                {"fixture-evidence-policy": "2.0.0"},
            ),
        )
        for dependency_inventory in inventories:
            with (
                self.subTest(inventory=dependency_inventory),
                self.assertRaises(SkillPackageError),
            ):
                validate_dependencies(manifest, dependency_inventory)

    def test_all_nonpublished_statuses_are_ineligible_and_inventory_is_snapshot(
        self,
    ) -> None:
        source = {"get_equipment_health": "1.0.0"}
        dependency_inventory = DependencyInventory(
            source, {"fixture-workflow": "1.0.0"}, {"fixture-evidence-policy": "1.0.0"}
        )
        source["get_equipment_health"] = "9.9.9"
        self.assertEqual(dependency_inventory.tools["get_equipment_health"], "1.0.0")
        for status in ("draft", "disabled", "retired"):
            with self.subTest(status=status), self.assertRaises(SkillPackageError):
                validate_dependencies(
                    parse_manifest(
                        FIXTURE.read_text(encoding="utf-8").replace(
                            '"status": "published"', f'"status": "{status}"'
                        )
                    ),
                    dependency_inventory,
                )


if __name__ == "__main__":
    unittest.main()
