from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
