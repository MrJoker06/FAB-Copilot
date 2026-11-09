"""SQLite feature shims shared by every connection the application opens.

Some Windows SQLite builds (for example Anaconda's) are compiled without
``SQLITE_ENABLE_MATH_FUNCTIONS``, while Cpk queries rely on ``SQRT``.  Python can
register the function per connection, so every opener in the app installs the
same set of helpers instead of assuming a particular build.  The shim mirrors
native ``SQRT`` argument coercion: only decimal text is accepted, while NULL,
blobs, non-numeric text and negatives return NULL.

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
import re
import sqlite3
from typing import Any

_TEMP_STORE_MODE: str | None = None

# SQLite only coerces text that is entirely a decimal literal (optionally
# surrounded by ASCII whitespace); anything else, including "inf", "nan", hex
# and non-ASCII digits, makes the native math functions return NULL.
_NUMERIC_TEXT = re.compile(
    r"[ \t\n\v\f\r]*"
    r"(?P<number>[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    r"[ \t\n\v\f\r]*"
)


def _numeric_argument(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        match = _NUMERIC_TEXT.fullmatch(value)
        if match is None:
            return None
        return float(match.group("number"))
    return None


def _sqrt(value: Any) -> float | None:
    """Mirror native ``SQRT``: NULL for NULL, blobs, non-numeric text and negatives."""
    number = _numeric_argument(value)
    if number is None or number < 0:
        return None
    return math.sqrt(number)


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


def install_sqlite_functions(
    connection: sqlite3.Connection, *, temp_store: str | None = None
) -> sqlite3.Connection:
    """Register helpers that are missing from some SQLite builds.

    Only real ``sqlite3.Connection`` objects are touched; wrappers and test
    doubles that merely mimic the connection protocol are returned unchanged.

    Only the application opener passes ``temp_store`` (resolved from the
    environment).  Portable adapters must not read the environment, so they
    reuse the mode already resolved in this process and otherwise keep the
    SQLite default.
    """
    if isinstance(connection, sqlite3.Connection):
        connection.create_function("SQRT", 1, _sqrt, deterministic=True)
        mode = temp_store or _TEMP_STORE_MODE
        if mode:
            connection.execute(f"PRAGMA temp_store={mode}")
    return connection
