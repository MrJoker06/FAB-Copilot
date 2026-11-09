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
from app.core.sqlite_support import _sqrt, install_sqlite_functions
from app.persistence.database import _connect_single

# Results observed from a SQLite 3.45 build compiled with native math functions.
NATIVE_SQRT_RESULTS = (
    (9, 3.0),
    (4, 2.0),
    (0, 0.0),
    (9.0, 3.0),
    (-1, None),
    (None, None),
    ("9", 3.0),
    (" 9 ", 3.0),
    ("\t9\n", 3.0),
    ("+9", 3.0),
    ("2.25", 1.5),
    (".25", 0.5),
    ("4.", 2.0),
    ("1e2", 10.0),
    ("-0", 0.0),
    ("-4", None),
    ("abc", None),
    ("9abc", None),
    ("9 x", None),
    ("", None),
    ("  ", None),
    ("1e", None),
    ("0x10", None),
    ("inf", None),
    ("nan", None),
    ("1_0", None),
    ("\u0669", None),
    (b"9", None),
)


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

    def test_shim_matches_native_sqrt_argument_coercion(self):
        for value, expected in NATIVE_SQRT_RESULTS:
            with self.subTest(value=value):
                self.assertEqual(_sqrt(value), expected)

    def test_shim_coerces_values_passed_through_sql(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        # A distinct name keeps the native SQRT (when present) from shadowing the shim.
        connection.create_function("SHIM_SQRT", 1, _sqrt, deterministic=True)
        for value, expected in NATIVE_SQRT_RESULTS:
            with self.subTest(value=value):
                row = connection.execute("SELECT SHIM_SQRT(?)", (value,)).fetchone()
                self.assertEqual(row[0], expected)
        self.assertEqual(
            connection.execute("SELECT SHIM_SQRT(CAST(9 AS TEXT))").fetchone()[0], 3.0
        )

    def test_install_registers_only_on_real_connections(self):
        class ConnectionDouble:
            def create_function(self, *args, **kwargs):
                raise AssertionError("test doubles must not be modified")

        double = ConnectionDouble()
        self.assertIs(install_sqlite_functions(double), double)

        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        self.assertIs(install_sqlite_functions(connection), connection)
        self.assertEqual(connection.execute("SELECT SQRT('9')").fetchone()[0], 3.0)

    def _apply_mode(self, mode: str, connection: sqlite3.Connection) -> int:
        original = sqlite_support._TEMP_STORE_MODE
        self.addCleanup(setattr, sqlite_support, "_TEMP_STORE_MODE", original)
        with patch.dict(os.environ, {"FAB_SQLITE_TEMP_STORE": mode}):
            sqlite_support._TEMP_STORE_MODE = None
            sqlite_support.install_sqlite_functions(
                connection, temp_store=sqlite_support.temp_store_mode()
            )
        return connection.execute("PRAGMA temp_store").fetchone()[0]

    def test_unresolved_mode_keeps_default_without_reading_environment(self):
        original = sqlite_support._TEMP_STORE_MODE
        self.addCleanup(setattr, sqlite_support, "_TEMP_STORE_MODE", original)
        sqlite_support._TEMP_STORE_MODE = None
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        with patch.object(sqlite_support.os, "getenv") as getenv, patch.dict(
            os.environ, {"FAB_SQLITE_TEMP_STORE": "memory"}
        ):
            sqlite_support.install_sqlite_functions(connection)
        getenv.assert_not_called()
        self.assertEqual(connection.execute("PRAGMA temp_store").fetchone()[0], 0)

    def test_adapters_reuse_mode_resolved_by_application_opener(self):
        original = sqlite_support._TEMP_STORE_MODE
        self.addCleanup(setattr, sqlite_support, "_TEMP_STORE_MODE", original)
        sqlite_support._TEMP_STORE_MODE = "MEMORY"
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        sqlite_support.install_sqlite_functions(connection)
        self.assertEqual(connection.execute("PRAGMA temp_store").fetchone()[0], 2)

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
