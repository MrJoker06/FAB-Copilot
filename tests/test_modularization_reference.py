from __future__ import annotations

import json
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import Mock

from scripts import build_modularization_reference as reference


class ModularizationReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        for name in reference.OVERLAYS + reference.FIXTURES:
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, project: Path, *args: str) -> bytes:
        if args[:2] == ("ls-tree", "-r"):
            return (
                b"100644 blob deadbeef\tapp/base.py\n"
                b"100644 blob deadbeef\tapp/evidence/semantics.py\n"
            )
        if args[0] == "show":
            return b"base"
        self.fail(f"unexpected git call: {args}")

    def _metadata(self, names: list[str] | None = None) -> dict:
        names = names or ["app/base.py"]
        return {
            "schema_version": "1.0",
            "reference_id": reference.REFERENCE_ID,
            "base_revision": reference.BASE_REVISION,
            "zip": "evaluations/reference.zip",
            "status": "frozen_reference_candidate",
            "members": [
                {
                    "path": name,
                    "source": (
                        "current-reviewed-overlay"
                        if name in reference.OVERLAYS
                        else "current-fixture"
                        if name in reference.FIXTURES
                        else f"git:{reference.BASE_REVISION}"
                    ),
                }
                for name in names
            ],
        }

    def _approved_metadata(self) -> dict:
        return {
            **self._metadata(),
            "status": "approved",
            "approval": {
                "reviewed_on": "2026-10-22",
                "source_audit": "passed",
                "behavior_baseline": reference.BEHAVIOR_BASELINE,
                "behavior_report": "evaluations/mod_002_behavior_report_v2.json",
            },
        }

    def _archive(self, name: str, members: list[tuple[str, int]] | None = None) -> Path:
        archive_path = self.project / name
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive_path, "w") as archive:
                for member, mode in (
                    [("app/base.py", stat.S_IFREG | 0o644)]
                    if members is None
                    else members
                ):
                    info = zipfile.ZipInfo(member)
                    info.external_attr = mode << 16
                    archive.writestr(info, b"content")
        return archive_path

    def test_build_members_has_base_overlays_and_fixed_fixtures(self) -> None:
        members = reference.build_members(self.project, self._git)

        self.assertEqual(
            members["app/base.py"], (f"git:{reference.BASE_REVISION}", b"base")
        )
        self.assertEqual(
            len(members), 2 + len(reference.OVERLAYS) + len(reference.FIXTURES)
        )
        self.assertEqual(
            members["app/evidence/semantics.py"][0], f"git:{reference.BASE_REVISION}"
        )
        self.assertNotIn("app/evidence/serialization.py", members)
        self.assertEqual(members[reference.OVERLAYS[0]][0], "current-reviewed-overlay")
        self.assertEqual(members[reference.FIXTURES[0]][0], "current-fixture")

    def test_base_members_rejects_bad_modes_and_ignores_non_app(self) -> None:
        bad_git = Mock(return_value=b"100755 blob deadbeef\tapp/base.py\n")
        with self.assertRaisesRegex(ValueError, "non-regular"):
            reference.base_members(self.project, bad_git)

        self.assertEqual(
            reference.base_members(
                self.project,
                Mock(return_value=b"100644 blob deadbeef\tstatic/logo.svg\n"),
            ),
            (),
        )

    def test_safe_member_rejects_noncanonical_and_unsafe_paths(self) -> None:
        for name in (
            "app//base.py",
            "app/./base.py",
            "app/../base.py",
            "app/base.py/",
            "app\\base.py",
            "/app/base.py",
            "app/C:base.py",
            "app/.env",
            "app/__pycache__/base.pyc",
            "app/cache.sqlite",
            "scripts/not-allowed.py",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                reference._safe_member(name)

    def test_base_members_rejects_noncanonical_git_path(self) -> None:
        git = Mock(return_value=b"100644 blob deadbeef\tapp/../base.py\n")
        with self.assertRaises(ValueError):
            reference.base_members(self.project, git)

    def test_overlay_symlink_escape_is_rejected(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        (outside / "identity.py").write_bytes(b"outside")
        overlay_parent = self.project / "app/core"
        for child in overlay_parent.iterdir():
            child.unlink()
        overlay_parent.rmdir()
        overlay_parent.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "unsafe overlay"):
            reference.build_members(self.project, self._git)

    def test_write_reference_refuses_existing_zip_before_git(self) -> None:
        output = self.project / "reference.zip"
        output.write_bytes(b"exists")
        git = Mock()
        with self.assertRaises(FileExistsError):
            reference.write_reference(
                self.project, output, self.project / "metadata.json", git
            )
        git.assert_not_called()

    def test_write_reference_refuses_existing_metadata_before_git(self) -> None:
        metadata = self.project / "metadata.json"
        metadata.write_text("{}", encoding="utf-8")
        git = Mock()
        with self.assertRaises(FileExistsError):
            reference.write_reference(
                self.project, self.project / "reference.zip", metadata, git
            )
        git.assert_not_called()

    def test_write_reference_preflight_rejects_invalid_targets_before_git(self) -> None:
        dangling = self.project / "dangling.zip"
        dangling.symlink_to(self.project / "missing.zip")
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        symlink_parent = self.project / "linked-output"
        symlink_parent.symlink_to(outside, target_is_directory=True)
        cases = (
            (self.project / "same", self.project / "same"),
            (dangling, self.project / "metadata.json"),
            (
                self.project / "missing" / "reference.zip",
                self.project / "metadata.json",
            ),
            (symlink_parent / "reference.zip", self.project / "metadata.json"),
        )
        for output, metadata in cases:
            git = Mock()
            with (
                self.subTest(output=output),
                self.assertRaises((ValueError, FileExistsError, FileNotFoundError)),
            ):
                reference.write_reference(self.project, output, metadata, git)
            git.assert_not_called()

    def test_write_reference_round_trip_creates_exclusive_candidate_files(self) -> None:
        output = self.project / "reference.zip"
        metadata_path = self.project / "metadata.json"

        reference.write_reference(self.project, output, metadata_path, self._git)

        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "frozen_reference_candidate")
        reference.validate_archive(output, payload)

    def test_validate_archive_rejects_duplicate_extra_missing_and_traversal_members(
        self,
    ) -> None:
        cases = (
            (
                [
                    ("app/base.py", stat.S_IFREG | 0o644),
                    ("app/base.py", stat.S_IFREG | 0o644),
                ],
                self._metadata(),
            ),
            (
                [
                    ("app/base.py", stat.S_IFREG | 0o644),
                    ("app/extra.py", stat.S_IFREG | 0o644),
                ],
                self._metadata(),
            ),
            ([], self._metadata()),
            (
                [("app/../base.py", stat.S_IFREG | 0o644)],
                self._metadata(["app/../base.py"]),
            ),
        )
        for index, (members, metadata) in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(ValueError):
                reference.validate_archive(
                    self._archive(f"case-{index}.zip", members), metadata
                )

    def test_validate_archive_rejects_symlink_mode_and_bad_metadata(self) -> None:
        archive = self._archive("mode.zip", [("app/base.py", stat.S_IFLNK | 0o777)])
        with self.assertRaises(ValueError):
            reference.validate_archive(archive, self._metadata())

        for metadata in (
            {**self._metadata(), "members": self._metadata()["members"] * 2},
            {
                **self._metadata(),
                "members": [{"path": "app/base.py", "source": "current-fixture"}],
            },
            {"reference_id": reference.REFERENCE_ID},
            {**self._metadata(), "schema_version": "2.0"},
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                reference.validate_archive(self._archive("metadata.zip"), metadata)

    def test_validate_archive_accepts_approved_metadata_and_rejects_bad_approval(
        self,
    ) -> None:
        archive = self._archive("approved.zip")
        reference.validate_archive(archive, self._approved_metadata())
        approved_on_24 = self._approved_metadata()
        approved_on_24["approval"]["reviewed_on"] = "2026-10-24"
        reference.validate_archive(archive, approved_on_24)

        for metadata in (
            {**self._metadata(), "status": "approved"},
            {**self._metadata(), "approval": self._approved_metadata()["approval"]},
            {
                **self._approved_metadata(),
                "approval": {"reviewed_on": "2026-10-22"},
            },
            {
                **self._approved_metadata(),
                "approval": {
                    **self._approved_metadata()["approval"],
                    "behavior_report": "/host/path/report.json",
                },
            },
            {
                **self._approved_metadata(),
                "approval": {
                    **self._approved_metadata()["approval"],
                    "reviewed_on": "2026-02-30",
                },
            },
            {
                **self._approved_metadata(),
                "approval": {
                    **self._approved_metadata()["approval"],
                    "reviewed_on": "20261024",
                },
            },
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                reference.validate_archive(archive, metadata)

    def test_existing_candidate_archive_validates(self) -> None:
        repository = Path(__file__).parents[1]
        metadata = json.loads(
            (repository / "evaluations/mod_002_reference_v4.json").read_text(
                encoding="utf-8"
            )
        )
        reference.validate_archive(
            repository / "evaluations/mod_002_reference_v4.zip", metadata
        )


if __name__ == "__main__":
    unittest.main()
