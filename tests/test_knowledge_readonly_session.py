from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from app.integrations.knowledge.runtime_search import _readonly_session


def _temp_dir() -> Path:
    """Create a writable scratch directory (mkdtemp yields 0o700 on Windows)."""
    path = Path(tempfile.gettempdir()) / f"fab-readonly-{uuid.uuid4().hex}"
    path.mkdir()
    return path


class ReadonlySessionTests(unittest.TestCase):
    def test_attaches_database_for_search_queries(self):
        """ATTACH must work on every platform, including Windows builds that
        ignore SQLITE_OPEN_URI and reject ``file://...?mode=ro`` in ATTACH."""
        tmp = _temp_dir()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "knowledge.db"
        seed = sqlite3.connect(path)
        seed.execute("CREATE TABLE chunks(chunk_id INTEGER PRIMARY KEY, title TEXT)")
        seed.execute("INSERT INTO chunks(chunk_id, title) VALUES (1, 'yield')")
        seed.commit()
        seed.close()

        with _readonly_session(path)() as session:
            row = session.execute("SELECT title FROM knowledge.chunks").fetchone()
            self.assertEqual(row["title"], "yield")

    def test_missing_source_raises(self):
        tmp = _temp_dir()
        self.addCleanup(shutil.rmtree, tmp, True)
        with self.assertRaises(RuntimeError):
            with _readonly_session(tmp / "absent.db")():
                pass


if __name__ == "__main__":
    unittest.main()
