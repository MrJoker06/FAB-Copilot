"""Process-local state for one isolated system-test module."""
from __future__ import annotations

import atexit
from contextlib import closing
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
REFERENCE_DEPARTMENTS = PROJECT_DIR / "data" / "departments"
_temporary_directory: Path | None = None


def _backup_database(source: Path, destination: Path) -> None:
    """Create a consistent SQLite snapshot without copying live WAL sidecars."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as source_connection, closing(sqlite3.connect(destination)) as target_connection:
        source_connection.backup(target_connection)


def _cleanup() -> None:
    global _temporary_directory
    if _temporary_directory is not None:
        shutil.rmtree(_temporary_directory, ignore_errors=True)
        _temporary_directory = None


def isolated_system_environment() -> Path:
    """Point app settings at disposable snapshots before importing app modules."""
    global _temporary_directory
    if _temporary_directory is not None:
        return _temporary_directory
    temporary_directory = Path(tempfile.mkdtemp(prefix="fab-insight-system-"))
    departments = temporary_directory / "departments"
    department_paths = {
        "FAB_MANUFACTURING_DATABASE_PATH": departments / "manufacturing_operations.db",
        "FAB_EQUIPMENT_DATABASE_PATH": departments / "equipment_engineering.db",
        "FAB_QUALITY_DATABASE_PATH": departments / "yield_quality.db",
        "FAB_KNOWLEDGE_DATABASE_PATH": departments / "process_knowledge.db",
        "FAB_AGENT_DATABASE_PATH": departments / "ai_operations.db",
    }
    try:
        for destination in department_paths.values():
            _backup_database(REFERENCE_DEPARTMENTS / destination.name, destination)
        os.environ.update({
            "FAB_DATABASE_DIR": str(departments),
            "FAB_DATABASE_PATH": str(temporary_directory / "fab_history.db"),
            **{key: str(value) for key, value in department_paths.items()},
            "FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH": str(temporary_directory / "personal_knowledge"),
            "AGENT_LOG_PATH": str(temporary_directory / "agent_events.jsonl"),
            "AGENT_RUN_LOG_DIR": str(temporary_directory / "agent"),
        })
    except BaseException:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise
    _temporary_directory = temporary_directory
    atexit.register(_cleanup)
    return temporary_directory
