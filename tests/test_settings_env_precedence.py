"""Environment-file precedence: process env > project ``.env`` > workspace ``.env``."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "FAB_ENV_PRECEDENCE_PROBE"
PROBE = f"import os, app.core.settings; print(os.environ.get({KEY!r}, '<unset>'))"


class SettingsEnvPrecedenceTests(unittest.TestCase):
    def _loaded_value(
        self, *, workspace: str | None, project: str | None, process: str | None
    ) -> str:
        with tempfile.TemporaryDirectory() as directory:
            workspace_file = Path(directory) / "workspace.env"
            project_file = Path(directory) / "project.env"
            for path, value in ((workspace_file, workspace), (project_file, project)):
                path.write_text(
                    "" if value is None else f"# comment\n{KEY}='{value}'\n",
                    encoding="utf-8",
                )
            environment = {
                name: value for name, value in os.environ.items() if name != KEY
            }
            environment.update(
                {
                    "FAB_WORKSPACE_ENV_FILE": str(workspace_file),
                    "FAB_PROJECT_ENV_FILE": str(project_file),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            if process is not None:
                environment[KEY] = process
            result = subprocess.run(
                [sys.executable, "-c", PROBE],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_project_env_file_overrides_workspace_env_file(self):
        self.assertEqual(
            self._loaded_value(workspace="workspace", project="project", process=None),
            "project",
        )

    def test_process_environment_overrides_both_env_files(self):
        self.assertEqual(
            self._loaded_value(
                workspace="workspace", project="project", process="process"
            ),
            "process",
        )

    def test_workspace_env_file_still_fills_keys_missing_from_project(self):
        self.assertEqual(
            self._loaded_value(workspace="workspace", project=None, process=None),
            "workspace",
        )

    def test_missing_env_files_leave_key_unset(self):
        self.assertEqual(
            self._loaded_value(workspace=None, project=None, process=None),
            "<unset>",
        )


if __name__ == "__main__":
    unittest.main()
