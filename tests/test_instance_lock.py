from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.instance_lock import is_locked, lock_path


class InstanceLockTests(unittest.TestCase):
    def test_nonblocking_lock_detects_real_subprocess_contention(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            instance = Path(temporary) / "instance"
            code = (
                "from pathlib import Path; from scripts.instance_lock import InstanceLock; "
                "import sys, time; lock=InstanceLock(Path(sys.argv[1])); "
                "assert lock.acquire(); print('locked', flush=True); time.sleep(2)"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", code, str(instance)],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(child.stdout.readline().strip(), "locked")
                self.assertTrue(is_locked(instance))
            finally:
                child.terminate()
                child.wait(timeout=5)
                child.stdout.close()
            self.assertFalse(is_locked(instance))

    def test_lock_location_matches_platform_contract(self) -> None:
        instance = Path("runtime") / "sample"
        path = lock_path(instance, Path("runtime"))
        if os.name == "nt":
            self.assertEqual(path, Path("runtime/.locks/sample.lock"))
        else:
            self.assertEqual(path, Path("runtime/sample/service.lock"))


if __name__ == "__main__":
    unittest.main()
