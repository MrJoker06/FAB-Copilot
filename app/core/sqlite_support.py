"""SQLite feature shims shared by every connection the application opens.

Some Windows SQLite builds (for example Anaconda's) are compiled without
``SQLITE_ENABLE_MATH_FUNCTIONS``, while Cpk queries rely on ``SQRT``.  Python can
register the function per connection, so every opener in the app installs the
same set of helpers instead of assuming a particular build.

The same helper also chooses where SQLite may spill temporary B-trees.  If the
process ``TMP``/``TEMP`` directory is not writable (locked-down Windows hosts,
sandboxes, or an unset variable resolving to the system directory), grouping a
large sensor table fails with ``unable to open database file``; falling back to
``PRAGMA temp_store=MEMORY`` keeps the analytical queries working.  The mode can
be pinned with ``FAB_SQLITE_TEMP_STORE=file`` or ``memory``.
"""

from __future__ import annotations

import math
import os
import sqlite3
from typing import Any

_TEMP_STORE_MODE: str | None = None


def _sqrt(value: Any) -> float | None:
    if value is None or value < 0:
        return None
    return math.sqrt(value)


def _temp_dir_writable(path: str) -> bool:
    probe = os.path.join(path, f".fab-sqlite-probe-{os.getpid()}")
    try:
        with open(probe, "wb"):
            pass
        os.unlink(probe)
    except OSError:
        return False
    return True


def temp_store_mode() -> str:
    """Return ``FILE`` or ``MEMORY`` for SQLite temporary storage."""
    global _TEMP_STORE_MODE
    if _TEMP_STORE_MODE is not None:
        return _TEMP_STORE_MODE
    configured = os.getenv("FAB_SQLITE_TEMP_STORE", "auto").strip().lower()
    if configured in {"file", "memory"}:
        _TEMP_STORE_MODE = configured.upper()
        return _TEMP_STORE_MODE
    for variable in ("TMP", "TEMP"):
        candidate = os.environ.get(variable)
        if candidate and os.path.isdir(candidate) and _temp_dir_writable(candidate):
            _TEMP_STORE_MODE = "FILE"
            return _TEMP_STORE_MODE
    _TEMP_STORE_MODE = "MEMORY"
    return _TEMP_STORE_MODE


def install_sqlite_functions(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Register helpers that are missing from some SQLite builds."""
    connection.create_function("SQRT", 1, _sqrt, deterministic=True)
    connection.execute(f"PRAGMA temp_store={temp_store_mode()}")
    return connection
