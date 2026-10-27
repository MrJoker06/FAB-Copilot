from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_repository


class RepositoryCheckTests(unittest.TestCase):
    def test_coverage_artifacts_are_ignored(self):
        rules = (Path(__file__).parents[1] / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".coverage", rules)
        self.assertIn(".coverage.*", rules)

    def test_hygiene_reports_lf_trailing_space_and_missing_final_newline(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.txt"
            path.write_bytes(b"bad  \r\nlast")
            with patch.object(check_repository, "PROJECT_DIR", Path(temporary)):
                errors = check_repository.text_hygiene_errors([path])
        self.assertEqual(errors, [
            "sample.txt: use LF line endings",
            "sample.txt: add a final newline",
            "sample.txt:1: remove trailing whitespace",
        ])

    def test_hygiene_skips_binary_and_non_utf8_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "image.bin"
            encoded = root / "legacy.bin"
            binary.write_bytes(b"\0\r")
            encoded.write_bytes(b"\xff")
            with patch.object(check_repository, "PROJECT_DIR", root):
                self.assertEqual(check_repository.text_hygiene_errors([binary, encoded]), [])

    def test_tracked_files_includes_cached_and_unignored_new_files_without_shell(self):
        completed = subprocess.CompletedProcess(["git"], 0, stdout=b"README.md\0")
        calls = []
        def runner(*args, **kwargs):
            calls.append(args[0])
            return completed
        with patch.object(check_repository, "PROJECT_DIR", Path("/repo")):
            files = check_repository.tracked_files(runner=runner)
        self.assertEqual(files, [Path("/repo/README.md")])
        self.assertEqual(calls, [["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]])

    def test_static_check_uses_bounded_compile_and_ruff_rules(self):
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
        check_repository.run_static(runner=runner)
        self.assertEqual(calls[0][1:5], ["-m", "compileall", "-q", "app"])
        self.assertEqual(calls[1][:5], [check_repository.sys.executable, "-m", "ruff", "check", "--select"])
        self.assertIn("E9,F63,F7,F82", calls[1])
        self.assertEqual(calls[2], [check_repository.sys.executable, "scripts/check_module_boundaries.py"])
        self.assertEqual(calls[3], [check_repository.sys.executable, "scripts/check_modularization_boundaries.py"])
