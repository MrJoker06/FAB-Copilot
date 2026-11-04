from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
