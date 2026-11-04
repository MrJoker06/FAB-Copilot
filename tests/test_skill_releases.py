"""Lifecycle checks for immutable, process-local Skill publications."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier
from unittest import mock

from app.skills.catalog import SkillReference
from app.skills.contracts import DependencyInventory, SkillPackageError
from app.skills.package import LoadedResource
from app.skills.releases import PublishedSkill, SkillReleaseStore

ROOT = Path("evaluations/skills/release_lifecycle_v1")
INVENTORY = DependencyInventory(
    {"get_equipment_health": "1.0.0"},
    {"fixture-workflow": "1.0.0"},
    {"fixture-evidence-policy": "1.0.0"},
)


def copy_fixture(target: Path, version: str) -> Path:
    shutil.copytree(ROOT / version, target)
    return target


class SkillReleaseTests(unittest.TestCase):
    def test_draft_publication_freezes_all_resources_without_editing_author(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            author = copy_fixture(Path(temporary) / "v1", "v1")
            store = SkillReleaseStore()
            release = store.publish(author, INVENTORY)
            self.assertEqual(
                (release.reference.skill_id, release.reference.version),
                ("release-validation", "1.0.0"),
            )
            self.assertEqual(release.manifest.status, "published")
            self.assertEqual(
                json.loads((author / "manifest.json").read_text(encoding="utf-8"))[
                    "status"
                ],
                "draft",
            )
            self.assertEqual(
                [item.path for item in release.resources],
                ["SKILL.md", "references/release.md"],
            )
            self.assertNotIn(str(author), repr(release))
            with self.assertRaises((FrozenInstanceError, AttributeError)):
                release.resources = ()  # type: ignore[misc]

    def test_exact_activation_disable_enable_and_rollback_have_no_implicit_latest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = SkillReleaseStore()
            one = store.publish(copy_fixture(root / "one", "v1"), INVENTORY).reference
            two = store.publish(copy_fixture(root / "two", "v2"), INVENTORY).reference
            with self.assertRaises(SkillPackageError) as error:
                store.active_reference(one.skill_id)
            self.assertEqual(error.exception.code, "unknown_skill")
            store.activate(one)
            self.assertEqual(store.active_reference(one.skill_id), one)
            store.activate(two)
            store.disable(two)
            with self.assertRaises(SkillPackageError) as error:
                store.active_reference(one.skill_id)
            self.assertEqual(error.exception.code, "unknown_skill")
            store.enable(two)
            with self.assertRaises(SkillPackageError):
                store.active_reference(one.skill_id)
            store.rollback(one)
            self.assertEqual(store.active_reference(one.skill_id), one)
            store.disable(one)
            with self.assertRaises(SkillPackageError) as error:
                store.rollback(one)
            self.assertEqual(error.exception.code, "ineligible_status")
            self.assertEqual(
                [
                    (item.reference.version, item.enabled, item.active)
                    for item in store.states()
                ],
                [("1.0.0", False, False), ("2.0.0", True, False)],
            )

    def test_duplicate_unknown_and_partial_publication_fail_without_replacement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            author = copy_fixture(root / "author", "v1")
            store = SkillReleaseStore()
            reference = store.publish(author, INVENTORY).reference
            store.disable(reference)
            with self.assertRaises(SkillPackageError) as error:
                store.publish(author, INVENTORY)
            self.assertEqual(error.exception.code, "duplicate_release")
            with self.assertRaises(SkillPackageError) as error:
                store.get(SkillReference("release-validation", "9.0.0"))
            self.assertEqual(error.exception.code, "unknown_skill")
            broken = copy_fixture(root / "broken", "v2")
            (broken / "references/release.md").unlink()
            with self.assertRaises(SkillPackageError):
                store.publish(broken, INVENTORY)
            disabled = copy_fixture(root / "disabled", "v2")
            manifest_path = disabled / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["status"] = "disabled"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(SkillPackageError) as error:
                store.publish(disabled, INVENTORY)
            self.assertEqual(error.exception.code, "ineligible_status")
            self.assertEqual(len(store.states()), 1)

    def test_frozen_loader_uses_author_content_after_change_or_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            author = copy_fixture(Path(temporary) / "author", "v1")
            store = SkillReleaseStore()
            reference = store.publish(author, INVENTORY).reference
            loader = store.loader(reference, INVENTORY)
            with self.assertRaises(AttributeError):
                loader.catalog = None  # type: ignore[misc]
            with self.assertRaises(AttributeError):
                loader.release = None  # type: ignore[misc]
            initial = loader.load(reference)
            (author / "SKILL.md").write_text("changed", encoding="utf-8")
            (author / "references/release.md").unlink()
            expanded = loader.expand(initial, ("references/release.md",))
            self.assertIn("Version one", expanded.loaded_resources[-1].text)
            self.assertIn("fixture v1", initial.loaded_resources[0].text)
            store.disable(reference)
            self.assertIn(
                "Version one",
                loader.expand(initial, ("references/release.md",))
                .loaded_resources[-1]
                .text,
            )
            with self.assertRaises(SkillPackageError) as error:
                store.loader(reference, INVENTORY)
            self.assertEqual(error.exception.code, "ineligible_status")

    def test_loader_uses_actual_inventory_and_publication_rejects_stale_source(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            author = copy_fixture(Path(temporary) / "author", "v2")
            store = SkillReleaseStore()
            reference = store.publish(author, INVENTORY).reference
            wrong = DependencyInventory(
                {"get_equipment_health": "2.0.0"},
                {"fixture-workflow": "1.0.0"},
                {"fixture-evidence-policy": "1.0.0"},
            )
            with self.assertRaises(SkillPackageError) as error:
                store.loader(reference, wrong)
            self.assertEqual(error.exception.code, "incompatible_dependency")
            other = copy_fixture(Path(temporary) / "other", "v1")
            with mock.patch(
                "app.skills.releases.SkillPackage.open",
                wraps=__import__(
                    "app.skills.releases", fromlist=["SkillPackage"]
                ).SkillPackage.open,
            ) as opened:
                original = opened._mock_wraps

                def drift(*args: object, **kwargs: object):
                    value = original(*args, **kwargs)
                    if opened.call_count == 2:
                        (other / "SKILL.md").write_text("drift", encoding="utf-8")
                    return value

                opened.side_effect = drift
                with self.assertRaises(SkillPackageError) as error:
                    SkillReleaseStore().publish(other, INVENTORY)
            self.assertEqual(error.exception.code, "stale_catalog")

    def test_concurrent_activation_never_exposes_a_disabled_active_reference(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = SkillReleaseStore()
            reference = store.publish(
                copy_fixture(Path(temporary) / "author", "v2"), INVENTORY
            ).reference
            start = Barrier(2)

            def assert_consistent() -> None:
                for state in store.states():
                    self.assertFalse(state.active and not state.enabled)

            def toggle_enabled() -> None:
                start.wait()
                for _ in range(128):
                    store.disable(reference)
                    assert_consistent()
                    store.enable(reference)
                    assert_consistent()

            def activate() -> None:
                start.wait()
                for _ in range(128):
                    try:
                        store.activate(reference)
                    except SkillPackageError as error:
                        self.assertEqual(error.code, "ineligible_status")
                    assert_consistent()

            with ThreadPoolExecutor(max_workers=2) as pool:
                toggle = pool.submit(toggle_enabled)
                activations = pool.submit(activate)
                toggle.result(timeout=10)
                activations.result(timeout=10)
            assert_consistent()

    def test_concurrent_same_version_publication_has_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            author = copy_fixture(Path(temporary) / "author", "v1")
            store = SkillReleaseStore()

            def publish() -> str:
                try:
                    store.publish(author, INVENTORY)
                    return "published"
                except SkillPackageError as error:
                    return error.code

            with ThreadPoolExecutor(max_workers=4) as pool:
                outcomes = list(pool.map(lambda _value: publish(), range(4)))
            self.assertEqual(outcomes.count("published"), 1)
            self.assertEqual(outcomes.count("duplicate_release"), 3)
            self.assertEqual(len(store.states()), 1)

    def test_cli_default_explicit_resource_and_cross_skill_upgrade_are_safe(
        self,
    ) -> None:
        script = Path(__file__).parents[1] / "scripts" / "demo_skill_releases.py"
        inventory = Path("evaluations/skills/catalog_discovery_inventory_v1.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = copy_fixture(root / "first", "v1")
            second = copy_fixture(root / "second", "v2")
            base = [
                sys.executable,
                str(script),
                "--package",
                str(first),
                "--upgrade-package",
                str(second),
                "--inventory",
                str(inventory),
            ]
            for command in (base, [*base, "--resource", "references/release.md"]):
                result = subprocess.run(
                    command, capture_output=True, text=True, check=False
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout)["old_loaded_paths"],
                    ["SKILL.md", "references/release.md"],
                )
            cross = copy_fixture(root / "cross", "v2")
            manifest_path = cross / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["skill_id"] = "other-skill"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = subprocess.run(
                [*base[:5], str(cross), *base[6:]],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(
                json.loads(result.stderr)["error_code"], "invalid_selection"
            )
            self.assertNotIn(str(cross), result.stderr)

    def test_direct_invalid_release_resources_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            author = copy_fixture(Path(temporary) / "author", "v2")
            release = SkillReleaseStore().publish(author, INVENTORY)
            with self.assertRaises(SkillPackageError):
                PublishedSkill(
                    release.reference,
                    release.manifest,
                    (LoadedResource("SKILL.md", "instructions", "x"),),
                    author.absolute(),
                )


if __name__ == "__main__":
    unittest.main()
