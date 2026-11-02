from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.skills.contracts import DependencyInventory, SkillPackageError
from app.skills.package import SkillPackage
from app.skills.resources import read_resource_text, validate_resource_path

ROOT = Path("evaluations/skills/manifest_validation_v1")
INVENTORY = DependencyInventory(
    {"get_equipment_health": "1.0.0"},
    {"fixture-workflow": "1.0.0"},
    {"fixture-evidence-policy": "1.0.0"},
)


def write_package(root: Path, sizes: list[int]) -> tuple[str, ...]:
    """Create an explicit temporary package with the requested declared files."""
    root.mkdir()
    manifest = json.loads(ROOT.joinpath("manifest.json").read_text(encoding="utf-8"))
    paths = [
        "SKILL.md",
        *(f"references/item-{index}.txt" for index in range(1, len(sizes))),
    ]
    manifest["resources"] = [
        {"path": path, "kind": "instructions" if index == 0 else "reference"}
        for index, path in enumerate(paths)
    ]
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for path, size in zip(paths, sizes, strict=True):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * size)
    return tuple(paths)


class SkillResourceTests(unittest.TestCase):
    def test_rejects_nonportable_names_and_undeclared_reads(self) -> None:
        for value in (
            "../secret",
            "C:/secret",
            "//host/file",
            "dir\\file",
            "file:stream",
            "CON",
            "COM¹",
            "a/../b",
            "a/",
            "a. ",
            "a?.txt",
        ):
            with self.subTest(value=value), self.assertRaises(SkillPackageError):
                validate_resource_path(value)
        package = SkillPackage.open(ROOT, INVENTORY)
        self.assertEqual(package.read_resources(("SKILL.md",))[0].path, "SKILL.md")
        with self.assertRaises(SkillPackageError):
            package.read_resources((["not-a-path"],))  # type: ignore[list-item]
        with self.assertRaises(SkillPackageError):
            package.read_resources(("manifest.json",))

    def test_bad_utf8_hardlink_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bad.txt").write_bytes(b"\xff")
            with self.assertRaises(SkillPackageError):
                read_resource_text(root, "bad.txt")
            source = root / "source.txt"
            source.write_text("safe", encoding="utf-8")
            linked = root / "linked.txt"
            try:
                os.link(source, linked)
            except OSError:
                self.skipTest("hard links unavailable")
            with self.assertRaises(SkillPackageError):
                read_resource_text(root, "linked.txt")
            outside = root.parent / "skill-outside.txt"
            outside.write_text("outside", encoding="utf-8")
            try:
                (root / "link.txt").symlink_to(outside)
            except OSError:
                return
            with self.assertRaises(SkillPackageError):
                read_resource_text(root, "link.txt")

    def test_bounded_large_fifo_and_swapped_leaf_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "large.txt").write_bytes(b"x" * (256 * 1024 + 1))
            with self.assertRaises(SkillPackageError):
                read_resource_text(root, "large.txt")
            if hasattr(os, "mkfifo"):
                os.mkfifo(root / "pipe")
                with self.assertRaises(SkillPackageError):
                    read_resource_text(root, "pipe")
            outside = root.parent / "swap-outside.txt"
            outside.write_text("outside", encoding="utf-8")
            target = root / "swapped.txt"
            target.write_text("inside", encoding="utf-8")
            try:
                target.unlink()
                target.symlink_to(outside)
            except OSError:
                return
            with self.assertRaises(SkillPackageError):
                read_resource_text(root, "swapped.txt")

    def test_many_tiny_resources_and_exact_aggregate_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tiny_root = Path(temporary) / "tiny"
            tiny_paths = write_package(tiny_root, [1, 1, 1, 1, 1])
            self.assertEqual(
                len(SkillPackage.open(tiny_root, INVENTORY).read_resources(tiny_paths)),
                5,
            )
            exact_root = Path(temporary) / "exact"
            exact_paths = write_package(exact_root, [256 * 1024] * 4)
            self.assertEqual(
                len(
                    SkillPackage.open(exact_root, INVENTORY).read_resources(exact_paths)
                ),
                4,
            )
            exceed_root = Path(temporary) / "exceed"
            exceed_paths = write_package(exceed_root, [256 * 1024] * 4 + [1])
            with self.assertRaises(SkillPackageError):
                SkillPackage.open(exceed_root, INVENTORY).read_resources(exceed_paths)

    def test_oversized_manifest_inert_python_and_read_failure_close_fd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_bytes(b"x" * (128 * 1024 + 1))
            with self.assertRaises(SkillPackageError):
                SkillPackage.open(root, INVENTORY)
            package_root = root / "package"
            paths = write_package(package_root, [1, 1])
            python_resource = package_root / "references/item-1.txt"
            python_resource.rename(package_root / "references/item-1.py")
            manifest = json.loads(
                (package_root / "manifest.json").read_text(encoding="utf-8")
            )
            manifest["resources"][1]["path"] = "references/item-1.py"
            (package_root / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (package_root / "references/item-1.py").write_text(
                "raise RuntimeError('must not execute')", encoding="utf-8"
            )
            self.assertIn(
                "must not execute",
                SkillPackage.open(package_root, INVENTORY)
                .read_resources(("references/item-1.py",))[0]
                .text,
            )
            captured: list[int] = []
            with (
                mock.patch(
                    "app.skills.resources.os.read",
                    side_effect=lambda fd, size: (
                        captured.append(fd),
                        (_ for _ in ()).throw(OSError("injected")),
                    )[1],
                ),
                self.assertRaises(SkillPackageError),
            ):
                read_resource_text(package_root, paths[0])
            self.assertTrue(captured)
            with self.assertRaises(OSError):
                os.fstat(captured[0])

    @unittest.skipUnless(os.name != "nt", "POSIX dirfd swap validation")
    def test_swap_immediately_before_leaf_open_never_reads_outside(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root.parent / "race-outside.txt"
            outside.write_text("outside", encoding="utf-8")
            target = root / "race.txt"
            target.write_text("inside", encoding="utf-8")
            original_open = os.open
            swapped = False

            def swapping_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal swapped
                if path == "race.txt" and not swapped:
                    swapped = True
                    target.unlink()
                    target.symlink_to(outside)
                return original_open(path, flags, *args, **kwargs)

            with (
                mock.patch("app.skills.resources.os.open", side_effect=swapping_open),
                self.assertRaises(SkillPackageError),
            ):
                read_resource_text(root, "race.txt")
            self.assertTrue(swapped)

    @unittest.skipUnless(os.name == "nt", "native Windows junction validation")
    def test_windows_junction_is_rejected_and_handles_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "note.txt").write_text("outside", encoding="utf-8")
            junction = root / "joined"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            with self.assertRaises(SkillPackageError):
                read_resource_text(root, "joined/note.txt")

    @unittest.skipUnless(os.name == "nt", "native Windows final-handle swap validation")
    def test_windows_directory_swap_before_open_never_reads_outside(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            inside = root / "safe"
            outside = Path(temporary) / "outside"
            inside.mkdir(parents=True)
            outside.mkdir()
            (inside / "note.txt").write_text("inside", encoding="utf-8")
            (outside / "note.txt").write_text("outside", encoding="utf-8")
            candidate = inside / "note.txt"
            original_open = os.open
            swapped = False

            def swapping_open(
                path: object, flags: int, *args: object, **kwargs: object
            ) -> int:
                nonlocal swapped
                if Path(path) == candidate and not swapped:
                    swapped = True
                    shutil.rmtree(inside)
                    result = subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(inside), str(outside)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                return original_open(path, flags, *args, **kwargs)

            with (
                mock.patch("app.skills.resources.os.open", side_effect=swapping_open),
                mock.patch("app.skills.resources.os.read") as read,
                self.assertRaises(SkillPackageError),
            ):
                read_resource_text(root, "safe/note.txt")
            self.assertTrue(swapped)
            read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
