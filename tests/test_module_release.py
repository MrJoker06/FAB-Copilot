"""Structural safety tests for the MOD-024 source-cohort delivery."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_module_release
import module_release


class ModuleReleaseTests(unittest.TestCase):
    def test_rejects_symlink_mode_on_declared_source_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            for label in ("source", "metadata"):
                with self.subTest(label=label):
                    delivery = self._build(Path(raw) / label)
                    release = json.loads(
                        (delivery / "module-release.json").read_text(encoding="utf-8")
                    )
                    part = release["archives"][0]
                    archive = delivery / part["filename"]
                    name = (
                        part["members"][0]
                        if label == "source"
                        else "module-artifact.json"
                    )
                    temporary = archive.with_suffix(".replacement")
                    with (
                        zipfile.ZipFile(archive) as source,
                        zipfile.ZipFile(temporary, "w") as target,
                    ):
                        for info in source.infolist():
                            data = source.read(info.filename)
                            if info.filename == name:
                                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                            target.writestr(info, data)
                    temporary.replace(archive)
                    with self.assertRaisesRegex(ValueError, "unsafe"):
                        install_module_release.read(delivery, ["tool_sources"])

    def test_rejects_noncanonical_paths_missing_sources_and_duplicate_artifacts(
        self,
    ) -> None:
        for member in (
            "app//alias.py",
            "app/./alias.py",
            "outside.py",
            "app/../outside.py",
            "app\\outside.py",
        ):
            with self.subTest(member=member), self.assertRaises(ValueError):
                install_module_release.safe(member)
        with tempfile.TemporaryDirectory() as raw:
            delivery = self._build(Path(raw) / "delivery")
            manifest = delivery / "module-release.json"
            original = manifest.read_text(encoding="utf-8")
            for label in ("archive", "artifact", "source", "anchor"):
                with self.subTest(label=label):
                    metadata = json.loads(original)
                    if label == "archive":
                        metadata["archives"][0]["filename"] = "..\\outside.zip"
                    elif label == "artifact":
                        metadata["archives"][0]["artifact"] = metadata["archives"][1][
                            "artifact"
                        ]
                    elif label == "source":
                        metadata["profiles"]["tool_sources"]["source_files"].append(
                            "app/missing.py"
                        )
                    else:
                        metadata["profiles"]["tool_sources"]["source_files"].remove(
                            "app/__init__.py"
                        )
                    manifest.write_text(
                        json.dumps(metadata), encoding="utf-8", newline="\n"
                    )
                    with self.assertRaises(ValueError):
                        install_module_release.read(delivery, ["tool_sources"])

    def test_rejects_system_python_and_incomplete_target_lock_without_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            delivery = self._build(Path(raw) / "delivery")
            release, _ = install_module_release.read(delivery, ["tool_sources"])
            base_python = Path(sys._base_executable)
            with self.assertRaisesRegex(ValueError, "virtual environment"):
                install_module_release.preflight_lock(
                    release, ["tool_sources"], None, base_python
                )
            python, target = self._fresh_target(Path(raw), with_pip=False)
            for lock in release["environment_locks"].values():
                del lock["profiles"]["tool_sources"]
            with self.assertRaisesRegex(ValueError, "dependency lock"):
                install_module_release.preflight_lock(
                    release, ["tool_sources"], None, python, target
                )
            self.assertFalse((target / "app").exists())

    def test_rejects_unlocked_transitive_dependency_from_resolver_report(self) -> None:
        def resolve(command, **kwargs):
            report = Path(command[command.index("--report") + 1])
            report.write_text(
                json.dumps(
                    {
                        "install": [
                            {
                                "metadata": {"name": "httpx", "version": "0.28.1"},
                                "download_info": {"url": "file:///offline/httpx.whl"},
                            },
                            {
                                "metadata": {"name": "extra", "version": "1.0"},
                                "download_info": {"url": "file:///offline/extra.whl"},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

        with (
            tempfile.TemporaryDirectory() as raw,
            patch.object(install_module_release.subprocess, "run", side_effect=resolve),
            self.assertRaisesRegex(ValueError, "locked BOM"),
        ):
            install_module_release._pip(
                Path(sys.executable), Path(raw), Path(raw), ["httpx==0.28.1"], True
            )

    def _build(self, root: Path) -> Path:
        module_release.build(root, build_id="test-build")
        self.assertEqual(module_release.verify(root)["members"], 307)
        return root

    @staticmethod
    def _fresh_target(root: Path, *, with_pip: bool) -> tuple[Path, Path]:
        virtual = root / "venv"
        venv.EnvBuilder(with_pip=with_pip).create(virtual)
        python = virtual / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        purelib = subprocess.check_output(
            [
                str(python),
                "-I",
                "-X",
                "utf8",
                "-c",
                "import sysconfig;print(sysconfig.get_paths()['purelib'])",
            ],
            text=True,
        ).strip()
        return python, Path(purelib)

    @staticmethod
    def _replace_part_metadata(
        archive: Path, mutate: Callable[[dict[str, object]], None]
    ) -> None:
        temporary = archive.with_suffix(".replacement")
        with (
            zipfile.ZipFile(archive) as source,
            zipfile.ZipFile(temporary, "w") as target,
        ):
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "module-artifact.json":
                    metadata = json.loads(data)
                    mutate(metadata)
                    data = (json.dumps(metadata, sort_keys=True) + "\n").encode()
                target.writestr(info, data)
        temporary.replace(archive)

    def test_real_release_has_exact_profiles_ownership_and_deterministic_parts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            first, second = Path(raw) / "first", Path(raw) / "second"
            module_release.build(first, build_id="fixed")
            module_release.build(second, build_id="fixed")
            release = json.loads(
                (first / "module-release.json").read_text(encoding="utf-8")
            )
            self.assertTrue((first / "install_module_release.py").is_file())
            self.assertTrue((first / "verify_module_release.py").is_file())
            self.assertEqual(len(release["ownership"]), 307)
            self.assertEqual(
                len(release["profiles"]["tool_sources"]["source_files"]), 104
            )
            self.assertEqual(
                len(release["profiles"]["skill_release"]["source_files"]), 107
            )
            self.assertEqual(
                len(release["profiles"]["model_transport"]["source_files"]), 5
            )
            union = set().union(
                *(set(item["source_files"]) for item in release["profiles"].values())
            )
            resources = set(release["profiles"]["skill_release"]["resource_files"])
            self.assertEqual(len(union), 149)
            self.assertEqual(len(union | resources), 153)
            self.assertTrue(
                all(name.startswith("app/") for name in release["ownership"])
            )
            self.assertTrue(
                any(name.endswith("/SKILL.md") for name in release["ownership"])
            )
            self.assertFalse(
                any(name.startswith("skill_assets/") for name in release["ownership"])
            )
            for part in release["archives"]:
                self.assertEqual(
                    (first / part["filename"]).read_bytes(),
                    (second / part["filename"]).read_bytes(),
                )

    def test_reader_rejects_member_metadata_ownership_and_case_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            delivery = self._build(Path(raw) / "delivery")
            release_path = delivery / "module-release.json"
            release = json.loads(release_path.read_text(encoding="utf-8"))
            member = next(iter(release["ownership"]))
            release["ownership"][member] = "wrong-artifact"
            release_path.write_text(json.dumps(release), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(ValueError, "unsafe or duplicate member"):
                install_module_release.read(delivery, ["tool_sources"])
            # A new valid delivery is used for malformed ZIP-member controls.
            delivery = self._build(Path(raw) / "second")
            release = json.loads(
                (delivery / "module-release.json").read_text(encoding="utf-8")
            )
            archive = delivery / release["archives"][0]["filename"]
            with zipfile.ZipFile(archive, "a") as handle:
                handle.writestr("../outside.py", b"x = 1\n")
            with self.assertRaisesRegex(ValueError, "archive shape|member mismatch"):
                install_module_release.read(delivery, ["skill_release"])
            delivery = self._build(Path(raw) / "third")
            release = json.loads(
                (delivery / "module-release.json").read_text(encoding="utf-8")
            )
            archive = delivery / release["archives"][0]["filename"]
            with zipfile.ZipFile(archive, "a") as handle:
                handle.writestr("APP/__init__.py", b"# duplicate folded path\n")
            with self.assertRaisesRegex(ValueError, "archive shape|member mismatch"):
                install_module_release.read(delivery, ["tool_sources"])

    def test_reader_rejects_cohort_version_missing_and_symlink_archive_tampering(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for label, mutate in (
                ("cohort", lambda metadata: metadata.update(cohort="other-cohort")),
                ("version", lambda metadata: metadata.update(version="999.0.0")),
            ):
                with self.subTest(label=label):
                    delivery = self._build(root / label)
                    release = json.loads(
                        (delivery / "module-release.json").read_text(encoding="utf-8")
                    )
                    self._replace_part_metadata(
                        delivery / release["archives"][0]["filename"], mutate
                    )
                    with self.assertRaisesRegex(ValueError, "cohort mismatch"):
                        install_module_release.read(delivery, ["tool_sources"])
            delivery = self._build(root / "missing")
            release = json.loads(
                (delivery / "module-release.json").read_text(encoding="utf-8")
            )
            (delivery / release["archives"][0]["filename"]).unlink()
            with self.assertRaises((OSError, ValueError)):
                install_module_release.read(delivery, ["tool_sources"])
            delivery = self._build(root / "symlink")
            release = json.loads(
                (delivery / "module-release.json").read_text(encoding="utf-8")
            )
            archive = delivery / release["archives"][0]["filename"]
            link = zipfile.ZipInfo("app/unsafe-link.py")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "a") as handle:
                handle.writestr(link, b"target\n")
            with self.assertRaisesRegex(ValueError, "archive shape|member mismatch"):
                install_module_release.read(delivery, ["tool_sources"])

    def test_preflight_rejects_foreign_target_before_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            delivery = self._build(Path(raw) / "delivery")
            python, target = self._fresh_target(Path(raw), with_pip=False)
            subprocess.run(
                [
                    str(python),
                    "-I",
                    "-X",
                    "utf8",
                    str(delivery / "install_module_release.py"),
                    "--delivery",
                    str(delivery),
                    "--target-python",
                    str(python),
                    "--target-site-packages",
                    str(target),
                    "--profiles",
                    "tool_sources",
                    "--verify",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse((target / "app").exists())
            app = target / "app"
            app.mkdir(parents=True)
            marker = app / "foreign.py"
            marker.write_text("marker = True\n", encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(ValueError, "foreign install"):
                install_module_release.install(
                    delivery, target, ["tool_sources"], python=python
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "marker = True\n")

    def test_missing_or_wrong_wheelhouse_is_rejected_without_install(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            delivery = self._build(Path(raw) / "delivery")
            python, target = self._fresh_target(Path(raw), with_pip=True)
            with self.assertRaisesRegex(ValueError, "offline wheelhouse"):
                install_module_release.install(
                    delivery, target, ["model_transport"], python=python
                )
            empty = Path(raw) / "empty-wheelhouse"
            empty.mkdir()
            with self.assertRaisesRegex(ValueError, "missing offline wheel"):
                install_module_release.install(
                    delivery, target, ["model_transport"], empty, python
                )
            self.assertFalse((target / "app").exists())


if __name__ == "__main__":
    unittest.main()
