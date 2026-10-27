from __future__ import annotations

import contextlib
import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.install_dispatcher_bundle import install, main

FILES = ["app/__init__.py", "app/demo.py"]


def metadata(files=FILES, **changes):
    value = {
        "schema_version": 1,
        "unit": "dispatcher_pilot",
        "version": "1.0.0",
        "external_dependencies": [],
        "files": files,
    }
    value.update(changes)
    return value


def write_member(archive, name, data, mode=0o644):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    archive.writestr(info, data)


def bundle(path, manifest=None, members=None, member_modes=None):
    manifest = metadata() if manifest is None else manifest
    members = (
        {"app/__init__.py": b"", "app/demo.py": b"value = 1\n"}
        if members is None
        else members
    )
    member_modes = {} if member_modes is None else member_modes
    with zipfile.ZipFile(path, "w") as archive:
        write_member(
            archive,
            "portable-unit.json",
            json.dumps(manifest).encode(),
            member_modes.get("portable-unit.json", 0o644),
        )
        for name, data in members.items():
            write_member(archive, name, data, member_modes.get(name, 0o644))


class DispatcherBundleSafetyTests(unittest.TestCase):
    def reject(self, path, target):
        sentinel = target.parent / "outside-sentinel"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaises(ValueError):
            install(path, target)
        self.assertFalse((target / "app").exists())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(target.glob("dispatcher-bundle-*")), [])

    def test_good_bundle_installs_and_existing_app_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive, target = root / "good.zip", root / "target"
            target.mkdir()
            bundle(archive)
            self.assertEqual(install(archive, target), 0)
            compile(
                (target / "app/demo.py").read_text(encoding="utf-8"), "demo", "exec"
            )
            marker = target / "app/marker"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(ValueError):
                install(archive, target)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            linked_target = root / "linked-target"
            linked_target.mkdir()
            sentinel = root / "symlink-sentinel"
            sentinel.mkdir()
            (linked_target / "app").symlink_to(sentinel, target_is_directory=True)
            with self.assertRaises(ValueError):
                install(archive, linked_target)
            self.assertTrue((linked_target / "app").is_symlink())

    def test_malformed_archives_never_create_app_or_stage(self):
        cases = {
            "paths": metadata(files=["app/__init__.py", "../x.py"]),
            "backslash": metadata(files=["app/__init__.py", "app\\x.py"]),
            "absolute": metadata(files=["app/__init__.py", "/app/x.py"]),
            "canonical": metadata(files=["app/__init__.py", "app//x.py"]),
            "dot": metadata(files=["app/__init__.py", "app/./x.py"]),
            "missing": metadata(files=["app/__init__.py"]),
            "anchor": metadata(files=["app/demo.py"]),
            "conflict": metadata(
                files=["app/__init__.py", "app/demo.py", "app/demo.py/x.py"]
            ),
            "schema-bool": metadata(schema_version=True),
            "schema-float": metadata(schema_version=1.0),
            "external": metadata(external_dependencies=["x"]),
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for label, manifest in cases.items():
                with self.subTest(label=label):
                    target = root / label
                    target.mkdir()
                    archive = root / f"{label}.zip"
                    bundle(archive, manifest)
                    self.reject(archive, target)
            for label, modes in (
                ("zero", {"app/demo.py": 0}),
                ("executable", {"app/demo.py": 0o755}),
                ("symlink", {"app/demo.py": 0o777}),
            ):
                with self.subTest(label=label):
                    target, archive = root / f"m-{label}", root / f"m-{label}.zip"
                    target.mkdir()
                    if label == "symlink":
                        with zipfile.ZipFile(archive, "w") as z:
                            write_member(
                                z, "portable-unit.json", json.dumps(metadata()).encode()
                            )
                            write_member(z, "app/__init__.py", b"")
                            info = zipfile.ZipInfo("app/demo.py")
                            info.create_system = 3
                            info.external_attr = (stat.S_IFLNK | 0o644) << 16
                            z.writestr(info, b"x")
                    else:
                        bundle(archive, member_modes=modes)
                    self.reject(archive, target)

    def test_content_and_zip_failures_are_sanitized(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bad_cases = {
                "syntax": {"app/__init__.py": b"", "app/demo.py": b"if:\n"},
                "crlf": {"app/__init__.py": b"", "app/demo.py": b"x = 1\r\n"},
                "extra": {"app/__init__.py": b"", "app/demo.py": b"", "extra.py": b""},
            }
            for label, members in bad_cases.items():
                target, archive = root / label, root / f"{label}.zip"
                target.mkdir()
                bundle(archive, members=members)
                self.reject(archive, target)
            duplicate, target = root / "duplicate.zip", root / "duplicate-target"
            target.mkdir()
            with zipfile.ZipFile(duplicate, "w") as archive:
                write_member(
                    archive, "portable-unit.json", json.dumps(metadata()).encode()
                )
                write_member(archive, "app/__init__.py", b"")
                write_member(archive, "app/demo.py", b"")
                write_member(archive, "app/demo.py", b"")
            self.reject(duplicate, target)
            oversized, target = root / "oversized.zip", root / "oversized-target"
            target.mkdir()
            bundle(
                oversized,
                members={"app/__init__.py": b"", "app/demo.py": b"x" * 2_000_001},
            )
            self.reject(oversized, target)
            invalid, target = root / "invalid.zip", root / "invalid-target"
            invalid.write_bytes(b"not a zip")
            target.mkdir()
            self.reject(invalid, target)
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(
                    main(["--bundle", str(invalid), "--target", str(target)]), 2
                )
            self.assertEqual(
                errors.getvalue().strip(), "dispatcher bundle installation failed"
            )
            self.assertNotIn(str(invalid), errors.getvalue())


if __name__ == "__main__":
    unittest.main()
