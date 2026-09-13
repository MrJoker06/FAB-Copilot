from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


class StartupScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        shutil.copy2(PROJECT_DIR / "run.sh", self.repo / "run.sh")
        (self.repo / "README.md").write_text("test source", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True)
        self.runtime = self.root / "runtime"
        self.log = self.root / "conda.log"
        self.conda = self.root / "fake-conda"
        self.conda.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s|%s|%s|%s\\n' \"$*\" \"$FAB_INSTANCE_ID\" \"$FAB_INSTANCE_ROOT\" \"$FAB_SOURCE_ROOT\" >> \"$FAKE_CONDA_LOG\"\n",
            encoding="utf-8",
        )
        self.conda.chmod(0o755)

    def tearDown(self):
        self.temporary.cleanup()

    def environment(self, **extra: str) -> dict[str, str]:
        result = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("FAB_")
            and key not in {"CONDA_DEFAULT_ENV", "PORT", "AGENT_LOG_PATH", "AGENT_RUN_LOG_DIR"}
        }
        result.update({
            "CONDA_EXE": str(self.conda),
            "CONDA_DEFAULT_ENV": "isolated-startup-test",
            "FAB_CONDA_ENV": "fab-insight-agent",
            "FAKE_CONDA_LOG": str(self.log),
            "FAB_INSTANCE_ROOT": str(self.runtime / "instance"),
            "HOME": str(self.root),
        })
        result.update(extra)
        return result

    def run_script(self, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "./run.sh"],
            cwd=self.repo,
            env=self.environment(**extra),
            text=True,
            capture_output=True,
            timeout=15,
        )

    def test_default_port_creates_isolated_manifest_and_invokes_seed_then_server(self):
        completed = self.run_script(FAB_INSTANCE_ID="offline-instance")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        instance = self.runtime / "instance"
        manifest = json.loads((instance / "instance.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["instance_id"], "offline-instance")
        self.assertEqual(manifest["port"], 8888)
        self.assertTrue((instance / "source" / ".fab-git-commit").is_file())
        self.assertTrue(self.log.is_file(), "fake CONDA_EXE was not invoked")
        calls = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(calls), 2)
        self.assertIn("-m app.manufacturing.seed", calls[0])
        self.assertIn("-m uvicorn app.main:app --host 127.0.0.1 --port 8888", calls[1])
        self.assertTrue(all("offline-instance" in call for call in calls))

    def test_rejects_invalid_instance_id_and_held_lock(self):
        invalid = self.run_script(FAB_INSTANCE_ID="bad/id")
        self.assertEqual(invalid.returncode, 2)
        lock_path = self.runtime / "instance" / "service.lock"
        lock_path.parent.mkdir(parents=True)
        lock_path.touch()
        with lock_path.open("r+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = self.run_script(FAB_INSTANCE_ID="locked")
        self.assertEqual(locked.returncode, 3)
        self.assertIn("already running", locked.stderr)

    def test_refuses_incomplete_or_mismatched_source_snapshot(self):
        source = self.runtime / "instance" / "source"
        source.mkdir(parents=True)
        incomplete = self.run_script(FAB_INSTANCE_ID="snapshot")
        self.assertEqual(incomplete.returncode, 4)
        commit = subprocess.check_output(["git", "rev-parse", "--short=12", "HEAD"], cwd=self.repo, text=True).strip()
        (source / ".fab-git-commit").write_text(f"not-{commit}\n", encoding="utf-8")
        mismatch = self.run_script(FAB_INSTANCE_ID="snapshot")
        self.assertEqual(mismatch.returncode, 5)
        self.assertIn("does not match", mismatch.stderr)


if __name__ == "__main__":
    unittest.main()
