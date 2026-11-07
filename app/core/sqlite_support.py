"""SQLite feature shims shared by every connection the application opens.

Some Windows SQLite builds (for example Anaconda's) are compiled without
``SQLITE_ENABLE_MATH_FUNCTIONS``, while Cpk queries rely on ``SQRT``.  Python can
register the function per connection, so every opener in the app installs the
same set of helpers instead of assuming a particular build.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any


def _sqrt(value: Any) -> float | None:
    if value is None or value < 0:
        return None
    return math.sqrt(value)


def install_sqlite_functions(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Register helpers that are missing from some SQLite builds."""
    connection.create_function("SQRT", 1, _sqrt, deterministic=True)
    return connection
