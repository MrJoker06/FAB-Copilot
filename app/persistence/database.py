"""Application-owned SQLite state (knowledge and agent operations).

Importing or initializing this module never creates demo manufacturing tables,
seeds sample rows, or imports demo_data. The default local demo composition lives
in app.demo_data.database and is selected explicitly by application bootstrap.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..core.settings import get_settings
from .connection import _connect_single, rows_to_dicts as rows_to_dicts
from .connection import sqlite_journal_mode
from .department_schemas import DEPARTMENT_SCHEMAS, SCHEMA_VERSION, TABLE_DEPARTMENTS
from .migrations import migrate_agent, migrate_knowledge


def department_paths() -> dict[str, Path]:
    settings = get_settings()
    return {
        "knowledge": settings.knowledge_database_path,
        "agent": settings.agent_database_path,
    }


def writable_table(name: str, path: Path | None = None) -> str:
    if path is not None:
        return name
    return f"{TABLE_DEPARTMENTS[name]}.{name}"


def _initialize_file(path: Path, departments: tuple[str, ...]) -> None:
    connection = _connect_single(path)
    try:
        connection.execute(f"PRAGMA journal_mode={sqlite_journal_mode(path)}")
        for department in departments:
            connection.executescript(DEPARTMENT_SCHEMAS[department])
            if department == "knowledge":
                migrate_knowledge(connection)
            else:
                migrate_agent(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, description) VALUES (?, ?) "
                "ON CONFLICT(version) DO UPDATE SET description = excluded.description",
                (SCHEMA_VERSION, f"department schema: {department}"),
            )
        connection.commit()
    finally:
        connection.close()


def initialize(path: Path | None = None) -> None:
    """Initialize application schemas only; never populate or attach business data."""
    if path is not None:
        _initialize_file(path, ("knowledge", "agent"))
    else:
        for department, target in department_paths().items():
            _initialize_file(target, (department,))


def connect(path: Path | None = None) -> sqlite3.Connection:
    if path is not None:
        return _connect_single(path)
    paths = department_paths()
    if any(not target.exists() for target in paths.values()):
        initialize()
    # A memory hub keeps both physical state stores writable under their stable
    # aliases without attaching the same main file a second time.
    connection = _connect_single(Path(":memory:"))
    try:
        for department, target in paths.items():
            connection.execute(f"ATTACH DATABASE ? AS {department}", (str(target),))
        for table, department in TABLE_DEPARTMENTS.items():
            connection.execute(
                f'CREATE TEMP VIEW "{table}" AS SELECT * FROM "{department}"."{table}"'
            )
        return connection
    except BaseException:
        connection.close()
        raise


@contextmanager
def db_session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        yield connection
    finally:
        connection.close()
