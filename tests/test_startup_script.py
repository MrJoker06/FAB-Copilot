from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run

PROJECT_DIR = Path(__file__).resolve().parents[1]


class StartupScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo with Unicode 测试"
        self.repo.mkdir()
        self._write_fixture()
        self._git("init", "-q")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Test")
        self._git("add", ".")
        self._git("commit", "-qm", "fixture")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, check=True)

    def _write_fixture(self) -> None:
        seed = self.repo / "app" / "demo_data" / "seed.py"
        seed.parent.mkdir(parents=True)
        (self.repo / "app" / "__init__.py").write_text("", encoding="utf-8")
        (seed.parent / "__init__.py").write_text("", encoding="utf-8")
        seed.write_text(
            "import json, os\n"
            "from pathlib import Path\n"
            "Path(os.environ['TEST_LAUNCH_LOG']).open('a', encoding='utf-8').write("
            "json.dumps({'step':'seed','days':__import__('sys').argv[-1],"
            "'db':os.environ['FAB_DATABASE_PATH'],'id':os.environ['FAB_INSTANCE_ID']}, ensure_ascii=False)+'\\n')\n"
            "raise SystemExit(int(os.environ.get('TEST_SEED_EXIT', '0')))\n",
            encoding="utf-8",
        )
        (self.repo / "uvicorn.py").write_text(
            "import json, os\n"
            "from pathlib import Path\n"
            "Path(os.environ['TEST_LAUNCH_LOG']).open('a', encoding='utf-8').write("
            "json.dumps({'step':'server','source':os.environ['FAB_SOURCE_MODE']}, "
            "ensure_ascii=False)+'\\n')\n"
            "raise SystemExit(int(os.environ.get('TEST_SERVER_EXIT', '0')))\n",
            encoding="utf-8",
        )
        (self.repo / "knowledge").mkdir()
        (self.repo / "README.md").write_text("fixture", encoding="utf-8")

    def _environment(self, instance: Path, log: Path, **extra: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {"FAB_INSTANCE_ROOT": str(instance), "TEST_LAUNCH_LOG": str(log)}
        )
        environment.update(extra)
        return environment

    def _launch(self, instance: Path, log: Path, *args: str, **extra: str) -> int:
        with (
            mock.patch.object(run, "PROJECT", self.repo),
            mock.patch.dict(
                os.environ, self._environment(instance, log, **extra), clear=True
            ),
        ):
            return run.main(["--seed-days", "1", *args])

    def test_snapshot_launches_seed_then_server_with_isolated_unicode_paths(
        self,
    ) -> None:
        instance = self.root / "runtime" / "实例 space"
        log = self.root / "launch.jsonl"
        self.assertEqual(self._launch(instance, log, "--source-mode", "snapshot"), 0)
        events = [
            json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([event["step"] for event in events], ["seed", "server"])
        self.assertEqual(events[0]["days"], "1")
        self.assertEqual(events[0]["id"], "space")
        self.assertTrue(events[0]["db"].startswith(str(instance)))
        manifest = json.loads((instance / "instance.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_mode"], "snapshot")
        self.assertEqual(manifest["platform"], os.name)
        self.assertTrue((instance / "source" / ".fab-git-commit").is_file())

    def test_snapshot_excludes_uncommitted_changes_and_worktree_includes_them(
        self,
    ) -> None:
        seed = self.repo / "app" / "demo_data" / "seed.py"
        seed.write_text(
            seed.read_text(encoding="utf-8").replace("'seed'", "'dirty'"),
            encoding="utf-8",
        )
        snapshot_log = self.root / "snapshot.jsonl"
        self.assertEqual(
            self._launch(self.root / "runtime" / "snapshot", snapshot_log), 0
        )
        self.assertEqual(
            json.loads(snapshot_log.read_text(encoding="utf-8").splitlines()[0])[
                "step"
            ],
            "seed",
        )
        worktree_log = self.root / "worktree.jsonl"
        self.assertEqual(
            self._launch(
                self.root / "runtime" / "worktree",
                worktree_log,
                "--source-mode",
                "worktree",
            ),
            0,
        )
        self.assertEqual(
            json.loads(worktree_log.read_text(encoding="utf-8").splitlines()[0])[
                "step"
            ],
            "dirty",
        )

    def test_snapshot_reuse_mismatch_and_invalid_input(self) -> None:
        instance = self.root / "runtime" / "reused"
        log = self.root / "launch.jsonl"
        self.assertEqual(self._launch(instance, log), 0)
        marker = instance / "source" / ".fab-git-commit"
        marker.write_text("other\n", encoding="utf-8")
        self.assertEqual(self._launch(instance, log), 5)
        self.assertEqual(
            self._launch(self.root / "runtime" / "other", log, "--port", "0"), 2
        )
        self.assertEqual(
            self._launch(
                self.root / "runtime" / "other", log, FAB_INSTANCE_ID="bad/id"
            ),
            2,
        )

    def test_export_copy_allowlist_excludes_runtime_and_user_workbook(self) -> None:
        export = self.root / "export"
        export.mkdir()
        shutil.copytree(self.repo / "app", export / "app")
        (export / "data").mkdir()
        (export / "data" / "secret.db").write_text("no", encoding="utf-8")
        (export / "user.xlsx").write_text("no", encoding="utf-8")
        copied = self.root / "copied"
        run._copy_export(export, copied)
        self.assertTrue((copied / "app" / "demo_data" / "seed.py").is_file())
        self.assertFalse((copied / "data").exists())
        self.assertFalse((copied / "user.xlsx").exists())

    def test_export_copy_rejects_nested_source_symlinks(self) -> None:
        export = self.root / "export"
        export.mkdir()
        shutil.copytree(self.repo / "app", export / "app")
        target = self.root / "outside.py"
        target.write_text("outside", encoding="utf-8")
        link = export / "app" / "linked.py"
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest(f"symlinks unavailable on this platform: {error}")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            run._copy_export(export, self.root / "copied")

    def test_server_error_propagates_without_leaving_a_held_lock(self) -> None:
        instance = self.root / "runtime" / "errors"
        log = self.root / "launch.jsonl"
        self.assertEqual(self._launch(instance, log, TEST_SERVER_EXIT="7"), 7)
        lock = run.InstanceLock(instance, instance.parent)
        self.assertTrue(lock.acquire())
        lock.release()

    def test_seed_error_propagates_without_starting_the_server(self) -> None:
        log = self.root / "launch.jsonl"
        self.assertEqual(
            self._launch(self.root / "runtime" / "seed-error", log, TEST_SEED_EXIT="9"),
            9,
        )
        self.assertEqual(
            [
                json.loads(line)["step"]
                for line in log.read_text(encoding="utf-8").splitlines()
            ],
            ["seed"],
        )

    def test_launcher_rejects_a_held_instance_lock(self) -> None:
        instance = self.root / "runtime" / "locked"
        instance.mkdir(parents=True)
        manifest = instance / "instance.json"
        manifest.write_text('{"instance_id":"locked","port":9999}', encoding="utf-8")
        original = manifest.read_bytes()
        lock = run.InstanceLock(instance, instance.parent)
        self.assertTrue(lock.acquire())
        try:
            self.assertEqual(self._launch(instance, self.root / "launch.jsonl"), 3)
        finally:
            lock.release()
        self.assertEqual(manifest.read_bytes(), original)
        self.assertFalse((instance / "source").exists())

    def test_invalid_port_environment_exits_without_runtime_writes(self) -> None:
        instance = self.root / "runtime" / "bad-port"
        with (
            mock.patch.object(run, "PROJECT", self.repo),
            mock.patch.dict(
                os.environ,
                {"PORT": "not-a-port", "FAB_INSTANCE_ROOT": str(instance)},
                clear=True,
            ),
            self.assertRaises(SystemExit) as error,
        ):
            run.main([])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(instance.exists())

    def test_scalar_manifest_is_rejected_without_traceback(self) -> None:
        instance = self.root / "runtime" / "scalar"
        instance.mkdir(parents=True)
        (instance / "instance.json").write_text("[]", encoding="utf-8")
        self.assertEqual(self._launch(instance, self.root / "launch.jsonl"), 4)

    def test_missing_dependency_diagnostic_has_no_runtime_side_effect(self) -> None:
        instance = self.root / "runtime" / "missing-dependency"
        with (
            mock.patch.object(run, "PROJECT", self.repo),
            mock.patch.object(run.importlib.util, "find_spec", return_value=None),
            mock.patch.dict(
                os.environ, {"FAB_INSTANCE_ROOT": str(instance)}, clear=True
            ),
        ):
            self.assertEqual(run.main([]), 2)
        self.assertFalse(instance.exists())

    def test_explicit_instance_id_is_preserved_when_directory_differs(self) -> None:
        instance = self.root / "runtime" / "directory-name"
        log = self.root / "explicit-id.jsonl"
        self.assertEqual(self._launch(instance, log, FAB_INSTANCE_ID="explicit-id"), 0)
        event = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(event["id"], "explicit-id")

    def test_project_overlapping_instance_root_is_rejected(self) -> None:
        with (
            mock.patch.object(run, "PROJECT", self.repo),
            mock.patch.dict(
                os.environ,
                {"FAB_INSTANCE_ROOT": str(self.repo / "app" / "runtime")},
                clear=True,
            ),
        ):
            self.assertEqual(run.main([]), 2)

    def test_snapshot_publish_falls_back_when_directory_rename_is_denied(self) -> None:
        staging = self.root / "instance" / ".source-stage"
        source = self.root / "instance" / "source"
        (staging / "app").mkdir(parents=True)
        (staging / "app" / "module.py").write_text("ready", encoding="utf-8")
        with mock.patch.object(Path, "replace", side_effect=PermissionError):
            run._publish_snapshot(staging, source, "commit")
        self.assertEqual(
            (source / "app" / "module.py").read_text(encoding="utf-8"), "ready"
        )
        self.assertEqual(
            (source / ".fab-git-commit").read_text(encoding="utf-8"), "commit\n"
        )
        self.assertFalse(staging.exists())

    def test_snapshot_publish_copy_failure_leaves_no_valid_marker(self) -> None:
        staging = self.root / "instance" / ".source-stage"
        source = self.root / "instance" / "source"
        (staging / "app").mkdir(parents=True)
        (staging / "app" / "module.py").write_text("ready", encoding="utf-8")
        with (
            mock.patch.object(Path, "replace", side_effect=PermissionError),
            mock.patch("run.shutil.copytree", side_effect=OSError("copy failed")),
            self.assertRaisesRegex(OSError, "copy failed"),
        ):
            run._publish_snapshot(staging, source, "commit")
        self.assertFalse((source / ".fab-git-commit").exists())

    def test_snapshot_publish_racing_creator_is_never_removed(self) -> None:
        staging = self.root / "instance" / ".source-stage"
        source = self.root / "instance" / "source"
        staging.mkdir(parents=True)
        original_mkdir = Path.mkdir

        def racing_mkdir(path: Path, *args: object, **kwargs: object) -> None:
            if path == source:
                original_mkdir(path, *args, **kwargs)
                (path / "sentinel").write_text("keep", encoding="utf-8")
                raise FileExistsError(path)
            original_mkdir(path, *args, **kwargs)

        with (
            mock.patch.object(Path, "replace", side_effect=PermissionError),
            mock.patch.object(Path, "mkdir", new=racing_mkdir),
            self.assertRaises(FileExistsError),
        ):
            run._publish_snapshot(staging, source, "commit")
        sentinel = source / "sentinel"
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_nested_directory_in_git_checkout_uses_export_mode(self) -> None:
        nested = self.repo / "export" / "project"
        nested.mkdir(parents=True)
        self.assertIsNone(run._git_commit(nested))

    def test_snapshot_symlink_outside_instance_is_rejected(self) -> None:
        instance = self.root / "runtime" / "linked"
        outside = self.root / "outside"
        outside.mkdir()
        instance.mkdir(parents=True)
        try:
            (instance / "source").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks unavailable on this platform: {error}")
        with self.assertRaisesRegex(RuntimeError, "outside"):
            run._snapshot(self.repo, instance, run._git_commit(self.repo))

    def test_check_is_side_effect_free_and_linux_wrapper_uses_requested_python(
        self,
    ) -> None:
        instance = self.root / "runtime" / "check"
        environment = os.environ.copy()
        environment.update(
            {"FAB_PYTHON": sys.executable, "FAB_INSTANCE_ROOT": str(instance)}
        )
        command = (
            ["cmd.exe", "/d", "/c", str(PROJECT_DIR / "run.bat"), "--check"]
            if os.name == "nt"
            else ["bash", str(PROJECT_DIR / "run.sh"), "--check"]
        )
        completed = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(completed.stdout)
        self.assertEqual(report["python"], sys.executable)
        self.assertFalse(instance.exists())
        self.assertNotIn(
            "wsl", (PROJECT_DIR / "run.bat").read_text(encoding="utf-8").lower()
        )

    def test_native_wrapper_propagates_invalid_port_exit_code(self) -> None:
        environment = os.environ.copy()
        environment["FAB_PYTHON"] = sys.executable
        command = (
            ["cmd.exe", "/d", "/c", str(PROJECT_DIR / "run.bat"), "--port", "0"]
            if os.name == "nt"
            else ["bash", str(PROJECT_DIR / "run.sh"), "--port", "0"]
        )
        completed = subprocess.run(
            command, cwd=PROJECT_DIR, env=environment, check=False
        )
        self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main()
