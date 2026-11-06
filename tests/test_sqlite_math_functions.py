from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.core import sqlite_support
from app.persistence.database import _connect_single


def _temp_dir() -> Path:
    """Create a writable scratch directory (mkdtemp yields 0o700 on Windows)."""
    path = Path(tempfile.gettempdir()) / f"fab-sql-fn-{uuid.uuid4().hex}"
    path.mkdir()
    return path


class SqliteMathFunctionTests(unittest.TestCase):
    def test_sqrt_is_available_on_every_build(self):
        """Cpk SQL uses SQRT(); some Windows SQLite builds omit math functions."""
        tmp = _temp_dir()
        self.addCleanup(shutil.rmtree, tmp, True)
        connection = _connect_single(tmp / "probe.db")
        self.addCleanup(connection.close)

        self.assertEqual(connection.execute("SELECT SQRT(9)").fetchone()[0], 3.0)

    def test_sqrt_matches_sqlite_null_semantics(self):
        tmp = _temp_dir()
        self.addCleanup(shutil.rmtree, tmp, True)
        connection = _connect_single(tmp / "probe.db")
        self.addCleanup(connection.close)

        self.assertIsNone(connection.execute("SELECT SQRT(-1)").fetchone()[0])
        self.assertIsNone(connection.execute("SELECT SQRT(NULL)").fetchone()[0])

    def _apply_mode(self, mode: str, connection: sqlite3.Connection) -> int:
        original = sqlite_support._TEMP_STORE_MODE
        self.addCleanup(setattr, sqlite_support, "_TEMP_STORE_MODE", original)
        with patch.dict(os.environ, {"FAB_SQLITE_TEMP_STORE": mode}):
            sqlite_support._TEMP_STORE_MODE = None
            sqlite_support.install_sqlite_functions(connection)
        return connection.execute("PRAGMA temp_store").fetchone()[0]

    def test_temp_store_can_be_pinned_for_hosts_with_read_only_temp(self):
        """A locked-down TMP makes SQLite temp B-trees fail; MEMORY is the fallback."""
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)

        self.assertEqual(self._apply_mode("memory", connection), 2)
        self.assertEqual(self._apply_mode("file", connection), 1)

    def test_auto_mode_falls_back_to_memory_when_temp_is_unusable(self):
        original = sqlite_support._TEMP_STORE_MODE
        self.addCleanup(setattr, sqlite_support, "_TEMP_STORE_MODE", original)
        with patch.dict(os.environ, {"FAB_SQLITE_TEMP_STORE": "auto"}):
            sqlite_support._TEMP_STORE_MODE = None
            with patch.dict(os.environ, {"TMP": "", "TEMP": ""}):
                self.assertEqual(sqlite_support.temp_store_mode(), "MEMORY")


if __name__ == "__main__":
    unittest.main()
