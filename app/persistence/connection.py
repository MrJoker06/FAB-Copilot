"""SQLite connection policy shared by application state and explicit demo stores."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from ..core.sqlite_support import install_sqlite_functions, temp_store_mode


def _connect_single(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=20000")
    install_sqlite_functions(connection, temp_store=temp_store_mode())
    return connection


def sqlite_journal_mode(path: Path) -> str:
    configured = os.getenv("FAB_SQLITE_JOURNAL_MODE", "auto").strip().upper()
    if configured in {"DELETE", "WAL", "TRUNCATE", "PERSIST"}:
        return configured
    if configured != "AUTO":
        raise ValueError(
            "FAB_SQLITE_JOURNAL_MODE 必须是 auto、DELETE、WAL、TRUNCATE 或 PERSIST"
        )
    return "DELETE" if path.absolute().as_posix().startswith("/mnt/") else "WAL"


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]
