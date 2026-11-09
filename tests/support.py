"""Small cross-platform helpers shared by the test suite."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


@contextmanager
def sqlite_session(path: str | Path, **kwargs: Any) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on error, then always close the connection.

    ``with sqlite3.connect(path) as connection`` only commits; it leaves the
    connection open.  On Windows that keeps the database file locked and makes a
    subsequent temporary-directory cleanup fail with ``PermissionError``.
    """
    connection = sqlite3.connect(path, **kwargs)
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def symlinks_supported() -> bool:
    """Return whether this process may create symbolic links."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        target = root / "target"
        target.write_text("x", encoding="utf-8")
        try:
            (root / "link").symlink_to(target)
        except (OSError, NotImplementedError):
            return False
    return True


SYMLINKS_SUPPORTED = symlinks_supported()

requires_symlinks = unittest.skipUnless(
    SYMLINKS_SUPPORTED,
    "filesystem does not allow symbolic links (Windows needs Developer Mode or elevation)",
)

# Keep the import face narrow for tests that only need the decorator.
__all__ = ["SYMLINKS_SUPPORTED", "requires_symlinks", "sqlite_session", "symlinks_supported"]
