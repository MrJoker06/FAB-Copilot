"""Application-owned SQLite state (knowledge and agent operations).

Importing or initializing this module never creates demo manufacturing tables,
seeds sample rows, or imports demo_data. The default local demo composition lives
in app.demo_data.database and is selected explicitly by application bootstrap.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from typing import Iterator

from ..core.settings import get_settings
from .connection import _connect_single, sqlite_journal_mode
from .connection import rows_to_dicts as rows_to_dicts
from .department_schemas import DEPARTMENT_SCHEMAS, SCHEMA_VERSION, TABLE_DEPARTMENTS
from .migrations import (
    _migrate_personal_knowledge_tags_source,
    migrate_agent,
    migrate_knowledge,
)

PERSONAL_TABLES = (
    "personal_knowledge_documents",
    "personal_knowledge_chunks",
    "personal_knowledge_jobs",
    "personal_knowledge_fts",
)


def _tables(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _drop_personal(connection):
    for table in reversed(PERSONAL_TABLES):
        connection.execute(f'DROP TABLE IF EXISTS "{table}"')


def _migration_marker(directory: Path) -> Path:
    return directory.parent / f".{directory.name}.separating"


def validate_layout(paths):
    values = list(paths.values())
    if len({p.resolve() for p in values}) != len(values) or any(
        a.exists() and b.exists() and a.samefile(b)
        for i, a in enumerate(values)
        for b in values[i + 1 :]
    ):
        raise ValueError("STORAGE_PATH_CONFLICT: database roles must be distinct")
    for target in (paths["agent"], paths["personal"]):
        if _migration_marker(target.parent).exists():
            raise RuntimeError(
                "RUNTIME_STORAGE_MIGRATION_PENDING: finish or recover the maintenance migration"
            )
    legacy_agent = paths["knowledge"].with_name("ai_operations.db")
    if (
        not paths["agent"].exists()
        and legacy_agent.exists()
        and legacy_agent.resolve() != paths["agent"].resolve()
    ):
        raise RuntimeError(
            "RUNTIME_STORAGE_MIGRATION_REQUIRED: run scripts/manage_databases.py separate-runtime before starting"
        )
    history = paths["knowledge"]
    if history.exists():
        with closing(
            sqlite3.connect(f"{history.resolve().as_uri()}?mode=ro", uri=True)
        ) as connection:
            existing = _tables(connection)
            if any(
                connection.execute(f'SELECT EXISTS(SELECT 1 FROM "{t}")').fetchone()[0]
                for t in PERSONAL_TABLES
                if t in existing
            ):
                raise RuntimeError(
                    "RUNTIME_STORAGE_MIGRATION_REQUIRED: personal data still resides in the history database"
                )


def separate_runtime_storage(
    knowledge: Path,
    agent: Path,
    destination: Path,
    *,
    results: Path | None = None,
    apply: bool = False,
) -> dict:
    """Explicit offline migration; source agent/results remain untouched backups.

    All writers must be stopped. SQLite write reservations reject concurrent
    writers; the pending marker blocks upgraded readers after an interrupted run.
    No model configuration is decoded, printed or replaced with defaults.
    """
    knowledge, agent, destination = (
        knowledge.resolve(),
        agent.resolve(),
        destination.resolve(),
    )
    if results is None and agent.with_name("tool_results.db").is_file():
        results = agent.with_name("tool_results.db")
    sources = {"history": knowledge, "agent": agent}
    if results is not None:
        sources["results"] = results.resolve()
    if any(not p.is_file() for p in sources.values()):
        raise ValueError("MIGRATION_SOURCE_MISSING")
    if any(
        a == b or a.samefile(b)
        for i, a in enumerate(sources.values())
        for b in list(sources.values())[i + 1 :]
    ):
        raise ValueError("STORAGE_PATH_CONFLICT")
    if any(p == destination or destination in p.parents for p in sources.values()):
        raise ValueError("STORAGE_PATH_CONFLICT")
    receipt_path = destination / "storage-separation.json"
    if _migration_marker(destination).exists():
        raise RuntimeError(
            "RUNTIME_STORAGE_MIGRATION_PENDING: inspect the maintenance backup before recovery"
        )
    if destination.exists():
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("status") == "completed" and receipt.get("sources") == {
                k: str(v) for k, v in sources.items()
            }:
                for name in ("ai_operations.db", "personal_knowledge.db") + (
                    ("tool_results.db",) if results else ()
                ):
                    if not (destination / name).is_file():
                        raise RuntimeError("MIGRATION_TARGET_INCOMPLETE")
                return {"status": "already_migrated"}
        raise FileExistsError(
            "MIGRATION_TARGET_EXISTS: refusing to overwrite runtime state"
        )
    if not apply:
        return {
            "status": "planned",
            "stores": ["agent", "personal"] + (["results"] if results else []),
            "history_pruned": False,
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    marker = _migration_marker(destination)
    backup = destination.parent / f"storage-backup-{uuid.uuid4().hex}"
    # Exclusive creation prevents two maintainers from publishing over each other.
    with marker.open("x", encoding="utf-8") as stream:
        json.dump({"backup": str(backup), "destination": str(destination)}, stream)
        stream.write("\n")
    stage = None
    published = False
    committed = False
    try:
        backup.mkdir()
        stage = Path(tempfile.mkdtemp(prefix=".storage-stage-", dir=destination.parent))
        with ExitStack() as stack:
            locks = {}
            for key, source in sources.items():
                connection = stack.enter_context(
                    closing(
                        sqlite3.connect(
                            f"{source.as_uri()}?mode=rw", uri=True, timeout=1
                        )
                    )
                )
                connection.execute("BEGIN IMMEDIATE")
                locks[key] = connection
                with (
                    closing(
                        sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
                    ) as reader,
                    closing(sqlite3.connect(backup / f"{key}.db")) as writer,
                ):
                    reader.backup(writer)
            for source_name, target_name in (
                ("agent", "ai_operations.db"),
                ("results", "tool_results.db"),
            ):
                if source_name in sources:
                    with (
                        closing(
                            sqlite3.connect(backup / f"{source_name}.db")
                        ) as reader,
                        closing(sqlite3.connect(stage / target_name)) as writer,
                    ):
                        reader.backup(writer)
            _initialize_file(stage / "personal_knowledge.db", ("personal",))
            with (
                closing(sqlite3.connect(backup / "history.db")) as original,
                closing(sqlite3.connect(stage / "personal_knowledge.db")) as personal,
            ):
                existing = _tables(original)
                for table in PERSONAL_TABLES:
                    if table not in existing:
                        continue
                    columns = [
                        r[1] for r in original.execute(f'PRAGMA table_info("{table}")')
                    ]
                    if table.endswith("_fts"):
                        columns.insert(0, "rowid")
                    fields = ",".join(f'"{c}"' for c in columns)
                    rows = original.execute(
                        f'SELECT {fields} FROM "{table}"'
                    ).fetchall()
                    placeholders = ",".join("?" for _ in columns)
                    personal.executemany(
                        f'INSERT INTO "{table}" ({fields}) VALUES ({placeholders})',
                        rows,
                    )
                    if (
                        table == "personal_knowledge_documents"
                        and "tags_source" not in columns
                    ):
                        personal.execute(
                            "UPDATE personal_knowledge_documents SET tags_source = 'user' "
                            "WHERE json_array_length(tags_json) > 0"
                        )
                personal.commit()
                _migrate_personal_knowledge_tags_source(personal)
                personal.commit()
            # Compare actual records, including FTS rowids, before pruning history.
            with (
                closing(sqlite3.connect(backup / "history.db")) as original,
                closing(sqlite3.connect(stage / "personal_knowledge.db")) as personal,
            ):
                existing = _tables(original)
                for table in PERSONAL_TABLES:
                    if table not in existing:
                        continue
                    columns = [
                        r[1] for r in original.execute(f'PRAGMA table_info("{table}")')
                    ]
                    fields = ",".join(f'"{c}"' for c in columns)
                    if table.endswith("_fts"):
                        fields = "rowid," + fields
                    before = original.execute(
                        f'SELECT {fields} FROM "{table}" ORDER BY rowid'
                    ).fetchall()
                    after = personal.execute(
                        f'SELECT {fields} FROM "{table}" ORDER BY rowid'
                    ).fetchall()
                    if before != after:
                        raise RuntimeError("MIGRATION_DATA_MISMATCH")
            for file in stage.glob("*.db"):
                with closing(sqlite3.connect(file)) as connection:
                    if (
                        connection.execute("PRAGMA quick_check").fetchone()[0] != "ok"
                        or connection.execute("PRAGMA foreign_key_check").fetchall()
                    ):
                        raise RuntimeError("MIGRATION_INTEGRITY_FAILED")
            receipt = {
                "version": 1,
                "status": "pending",
                "sources": {k: str(v) for k, v in sources.items()},
                "backup": str(backup),
            }
            (stage / "storage-separation.json").write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
            destination.mkdir()  # exclusive reservation, never replace an existing directory
            published = True
            for file in stage.iterdir():
                file.rename(destination / file.name)
            _drop_personal(locks["history"])
            locks["history"].commit()
            committed = True
            receipt["status"] = "completed"
            temporary_receipt = destination / ".storage-separation.json.tmp"
            temporary_receipt.write_text(
                json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
            )
            temporary_receipt.replace(receipt_path)
        marker.unlink()
        return {
            "status": "completed",
            "backup": str(backup),
            "stores": ["agent", "personal"] + (["results"] if results else []),
        }
    except BaseException:
        # Before the history commit, SQLite rolls back and the old stores are
        # authoritative. After commit, retain marker/receipt for explicit recovery.
        if not committed:
            if published:
                for file in destination.iterdir():
                    file.unlink()
                destination.rmdir()
            marker.unlink(missing_ok=True)
        raise
    finally:
        if stage is not None:
            shutil.rmtree(stage)


def department_paths() -> dict[str, Path]:
    settings = get_settings()
    paths = {
        "knowledge": settings.knowledge_database_path,
        "agent": settings.agent_database_path,
        "personal": settings.personal_database_path
        or settings.agent_database_path.with_name("personal_knowledge.db"),
    }
    if len({value.resolve() for value in paths.values()}) != len(paths) or any(
        a.exists() and b.exists() and a.samefile(b)
        for i, a in enumerate(paths.values())
        for b in list(paths.values())[i + 1 :]
    ):
        raise ValueError(
            "STORAGE_PATH_CONFLICT: history, agent and personal databases must be distinct"
        )
    return paths


def writable_table(name: str, path: Path | None = None) -> str:
    if path is not None:
        return name
    return f"{TABLE_DEPARTMENTS[name]}.{name}"


def _initialize_file(path: Path, departments: tuple[str, ...]) -> None:
    connection = _connect_single(path)
    try:
        connection.execute(f"PRAGMA journal_mode={sqlite_journal_mode(path)}")
        for department in departments:
            if department == "knowledge" and len(departments) == 1:
                # No data is migrated implicitly; obsolete empty tables only.
                existing = _tables(connection)
                if any(
                    connection.execute(
                        f'SELECT EXISTS(SELECT 1 FROM "{t}")'
                    ).fetchone()[0]
                    for t in PERSONAL_TABLES
                    if t in existing
                ):
                    raise RuntimeError("RUNTIME_STORAGE_MIGRATION_REQUIRED")
                _drop_personal(connection)
            connection.executescript(DEPARTMENT_SCHEMAS[department])
            if department == "knowledge":
                migrate_knowledge(connection)
            elif department == "agent":
                migrate_agent(connection)
            else:
                _migrate_personal_knowledge_tags_source(connection)
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
        _initialize_file(path, ("knowledge", "agent", "personal"))
    else:
        paths = department_paths()
        validate_layout(paths)
        for department, target in paths.items():
            _initialize_file(target, (department,))


def connect(path: Path | None = None) -> sqlite3.Connection:
    if path is not None:
        return _connect_single(path)
    paths = department_paths()
    validate_layout(paths)
    if any(not target.exists() for target in paths.values()):
        initialize()
    # A memory hub keeps the physical stores writable under their stable
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
