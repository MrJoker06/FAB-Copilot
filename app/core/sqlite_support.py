"""SQLite feature shims shared by every connection the application opens.

Some Windows SQLite builds (for example Anaconda's) are compiled without
``SQLITE_ENABLE_MATH_FUNCTIONS``, while Cpk queries rely on ``SQRT``.  Python can
register the function per connection, so every opener in the app installs the
same set of helpers instead of assuming a particular build.
"""

from __future__ import annotations

import math
import re
import sqlite3
from typing import Any

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


def install_sqlite_functions(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Register helpers that are missing from some SQLite builds.

    Only real ``sqlite3.Connection`` objects are touched; wrappers and test
    doubles that merely mimic the connection protocol are returned unchanged.
    """
    if isinstance(connection, sqlite3.Connection):
        connection.create_function("SQRT", 1, _sqrt, deterministic=True)
    return connection
