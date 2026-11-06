"""Project test package so ``python -m unittest discover`` finds the suite."""

from __future__ import annotations

import gc
import tempfile
import time

_original_cleanup = tempfile.TemporaryDirectory.cleanup


def _cleanup_with_windows_retry(self: tempfile.TemporaryDirectory) -> None:
    """Collect leaked SQLite handles before removing a temporary directory.

    Several fixtures build their databases with ``with sqlite3.connect(...)``.
    That context manager commits, but it does not close the connection, and on
    Windows the database file stays locked until the connection object is
    collected.  A plain ``cleanup()`` then fails with ``PermissionError
    [WinError 32]`` even though the test itself passed.  Collect cycles first
    and retry briefly so the same suite passes on Windows and POSIX.
    """
    for attempt in range(10):
        gc.collect()
        try:
            _original_cleanup(self)
            return
        except OSError:
            # Windows also reports a closing handle as a non-empty directory
            # (WinError 145) or a chmod denial (WinError 5).  Defender/indexers
            # can hold freshly written files for several seconds, so back off
            # a little longer before treating the directory as stuck.
            if attempt == 9:
                raise
            time.sleep(0.25 * (attempt + 1))


tempfile.TemporaryDirectory.cleanup = _cleanup_with_windows_retry  # type: ignore[method-assign]
