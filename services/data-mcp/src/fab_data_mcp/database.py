from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .settings import DataMCPSettings


def _readonly_uri(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"database does not exist: {path}")
    return f"file:{path.as_posix()}?mode=ro"


def connect_readonly(settings: DataMCPSettings) -> sqlite3.Connection:
    paths = settings.resolved_database_paths()
    connection = sqlite3.connect(_readonly_uri(paths["main"]), uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        for schema in ("equipment", "quality"):
            connection.execute(f"ATTACH DATABASE ? AS {schema}", (_readonly_uri(paths[schema]),))
        connection.execute("PRAGMA query_only=ON")
        return connection
    except Exception:
        connection.close()
        raise


@contextmanager
def readonly_session(settings: DataMCPSettings) -> Iterator[sqlite3.Connection]:
    connection = connect_readonly(settings)
    try:
        yield connection
    finally:
        connection.close()


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, object]]:
    return [dict(row) for row in rows]
