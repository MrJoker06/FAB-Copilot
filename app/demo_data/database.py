"""Local demo database composition, migration, sample catalog and horizon checks.

This module is deliberately opt-in. Application storage can be initialized and
used without importing this module or shipping the demo_data package.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from ..core.settings import get_settings
from ..persistence import database as application_storage
from ..persistence.connection import _connect_single, sqlite_journal_mode
from ..persistence.migrations import (
    CASE_GOVERNANCE_COLUMNS,
    CHAT_SESSION_COLUMNS,
    CHAT_MESSAGE_COLUMNS,
    _migrate_agent_runs,
    _migrate_agent_tool_events,
    _migrate_model_catalog_capabilities,
    _migrate_model_catalog_compatibility,
    _migrate_model_health,
    _migrate_personal_knowledge_tags_source,
)
from .schemas import (
    SCHEMA,
    PROCESS_RUN_MEASUREMENT_COLUMNS,
    DEPARTMENT_SCHEMAS,
    MIGRATION_ORDER,
    SCHEMA_VERSION,
    TABLE_DEPARTMENTS,
)

DEFAULT_DEFECT_TYPE_ALIASES = {
    "Scratch": ("scratch", "划伤"),
    "Thickness": ("thickness", "膜厚"),
    "Non-uniformity": ("non-uniformity", "uniformity", "均匀性", "不均匀"),
    "Particle": ("particle", "颗粒"),
    "Overlay": ("overlay", "套刻"),
    "Focus": ("focus", "焦距"),
    "CD Shift": ("cd shift", "cd偏移"),
    "Residue": ("residue", "残留"),
    "Dishing": ("dishing", "蝶形凹陷"),
    "Yield": ("yield", "良率"),
    "Cycle Time": ("cycle time", "周期时间"),
    "Peeling": ("peeling", "剥落"),
    "Sheet Resistance": ("sheet resistance", "片阻"),
    "Dose Shift": ("dose shift", "剂量偏移"),
    "Watermark": ("watermark", "水印"),
    "Metal Contamination": ("metal contamination", "金属污染"),
    "Measurement Drift": ("measurement drift", "量测漂移", "测量漂移"),
    "Micro-trench": ("micro-trench", "微沟槽"),
    "Erosion": ("erosion", "侵蚀"),
    "Slip": ("slip", "滑移"),
    "Oxide Non-uniformity": ("oxide non-uniformity", "氧化层不均匀"),
    "Channeling": ("channeling", "沟道效应"),
    "False Defect": ("false defect", "误报缺陷"),
    "Correlation": ("correlation", "相关性"),
    "Repeat Alarm": ("repeat alarm", "重复报警"),
}


def _seed_default_defect_types(
    connection: sqlite3.Connection, schema: str = ""
) -> None:
    """Ensure the governed defect catalog contains every built-in type."""
    prefix = f"{schema}." if schema else ""
    for canonical_name, aliases in DEFAULT_DEFECT_TYPE_ALIASES.items():
        connection.execute(
            f"INSERT OR IGNORE INTO {prefix}defect_types(canonical_name) VALUES (?)",
            (canonical_name,),
        )
        defect_type_id = connection.execute(
            f"SELECT defect_type_id FROM {prefix}defect_types WHERE canonical_name = ?",
            (canonical_name,),
        ).fetchone()[0]
        connection.executemany(
            f"INSERT OR IGNORE INTO {prefix}defect_type_aliases(defect_type_id, alias) VALUES (?, ?)",
            ((defect_type_id, alias) for alias in aliases),
        )


def department_paths() -> dict[str, Path]:
    settings = get_settings()
    return {
        "main": settings.manufacturing_database_path,
        "equipment": settings.equipment_database_path,
        "quality": settings.quality_database_path,
        "knowledge": settings.knowledge_database_path,
        "agent": settings.agent_database_path,
    }


def writable_table(name: str, path: Path | None = None) -> str:
    """Return a physical table name for writes; reads use compatibility views."""
    if path is not None:
        return name
    department = TABLE_DEPARTMENTS[name]
    return name if department == "main" else f"{department}.{name}"


def _initialize_legacy(path: Path) -> None:
    connection = _connect_single(path)
    try:
        connection.execute(f"PRAGMA journal_mode={sqlite_journal_mode(path)}")
        connection.executescript(SCHEMA)
        _migrate_personal_knowledge_tags_source(connection)
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(historical_cases)")
        }
        for name, definition in CASE_GOVERNANCE_COLUMNS.items():
            if name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE historical_cases ADD COLUMN {name} {definition}"
                )
        run_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(process_runs)")
        }
        for name, definition in PROCESS_RUN_MEASUREMENT_COLUMNS.items():
            if name not in run_columns:
                connection.execute(
                    f"ALTER TABLE process_runs ADD COLUMN {name} {definition}"
                )
        session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chat_sessions)")
        }
        for name, definition in CHAT_SESSION_COLUMNS.items():
            if name not in session_columns:
                connection.execute(
                    f"ALTER TABLE chat_sessions ADD COLUMN {name} {definition}"
                )
        message_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chat_messages)")
        }
        for name, definition in CHAT_MESSAGE_COLUMNS.items():
            if name not in message_columns:
                connection.execute(
                    f"ALTER TABLE chat_messages ADD COLUMN {name} {definition}"
                )
        _migrate_agent_runs(connection)
        _migrate_agent_tool_events(connection)
        _migrate_model_catalog_capabilities(connection)
        _migrate_model_catalog_compatibility(connection)
        _migrate_model_health(connection)
        connection.execute(
            """INSERT INTO schema_migrations(version, description) VALUES (?, 'legacy schema')
               ON CONFLICT(version) DO UPDATE SET description = excluded.description""",
            (SCHEMA_VERSION,),
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_client_id "
            "ON chat_messages(session_id, client_message_id) "
            "WHERE role = 'user' AND client_message_id IS NOT NULL"
        )
        _seed_default_defect_types(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_cases_governance ON historical_cases(case_status, process_step, defect_type)"
        )
        connection.commit()
    finally:
        connection.close()


def _initialize_departments() -> None:
    application_storage.initialize()
    paths = department_paths()
    for department, path in paths.items():
        if department in {"knowledge", "agent"}:
            continue
        connection = _connect_single(path)
        try:
            connection.execute(f"PRAGMA journal_mode={sqlite_journal_mode(path)}")
            connection.executescript(DEPARTMENT_SCHEMAS[department])
            connection.execute(
                """INSERT INTO schema_migrations(version, description) VALUES (?, ?)
                   ON CONFLICT(version) DO UPDATE SET description = excluded.description""",
                (SCHEMA_VERSION, f"department schema: {department}"),
            )
            if department == "quality":
                _seed_default_defect_types(connection)
            connection.commit()
        finally:
            connection.close()


def connect(path: Path | None = None) -> sqlite3.Connection:
    if path is not None:
        return _connect_single(path)
    paths = department_paths()
    if any(not item.exists() for item in paths.values()):
        _initialize_departments()
    connection = _connect_single(paths["main"])
    for department in ("equipment", "quality", "knowledge", "agent"):
        connection.execute(
            f"ATTACH DATABASE ? AS {department}", (str(paths[department]),)
        )
    for table, department in TABLE_DEPARTMENTS.items():
        if department == "main":
            continue
        connection.execute(
            f'CREATE TEMP VIEW "{table}" AS SELECT * FROM "{department}"."{table}"'
        )
    return connection


def initialize(path: Path | None = None) -> None:
    if path is not None:
        _initialize_legacy(path)
    else:
        _initialize_departments()


def migrate_legacy_database(
    source: Path | None = None, force: bool = False
) -> dict[str, int]:
    """Copy the legacy monolith into department-owned databases without modifying it."""
    source_path = source or get_settings().database_path
    if not source_path.exists():
        return {}
    initialize()
    aliases = {
        "main": "manufacturing",
        "equipment": "equipment",
        "quality": "quality",
        "knowledge": "knowledge",
        "agent": "agent",
    }
    connection = _connect_single(source_path)
    try:
        source_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "lots" not in source_tables:
            return {}
        for department, target_path in department_paths().items():
            connection.execute(
                f"ATTACH DATABASE ? AS {aliases[department]}",
                (str(target_path),),
            )
        existing_lots = connection.execute(
            "SELECT COUNT(*) FROM manufacturing.lots"
        ).fetchone()[0]
        if existing_lots and not force:
            return {}
        connection.execute("PRAGMA foreign_keys=OFF")
        for table in reversed(MIGRATION_ORDER):
            target_alias = aliases[TABLE_DEPARTMENTS[table]]
            connection.execute(f'DELETE FROM "{target_alias}"."{table}"')
        counts: dict[str, int] = {}
        for table in MIGRATION_ORDER:
            if table not in source_tables:
                counts[table] = 0
                continue
            target_alias = aliases[TABLE_DEPARTMENTS[table]]
            source_columns = {
                row[1]
                for row in connection.execute(f"PRAGMA main.table_info('{table}')")
            }
            target_columns = [
                row[1]
                for row in connection.execute(
                    f"PRAGMA {target_alias}.table_info('{table}')"
                )
                if row[1] in source_columns
            ]
            columns = ", ".join(f'"{column}"' for column in target_columns)
            connection.execute(
                f'INSERT INTO "{target_alias}"."{table}" ({columns}) '
                f'SELECT {columns} FROM main."{table}"'
            )
            counts[table] = connection.execute(
                f'SELECT COUNT(*) FROM "{target_alias}"."{table}"'
            ).fetchone()[0]

        connection.execute(
            """UPDATE quality.wafer_maps
               SET detected_time = COALESCE(
                   (SELECT MAX(r.run_time) FROM manufacturing.process_runs r
                    WHERE r.lot_id = quality.wafer_maps.lot_id
                      AND datetime(r.run_time) <= CURRENT_TIMESTAMP),
                   (SELECT l.start_time FROM manufacturing.lots l
                    WHERE l.lot_id = quality.wafer_maps.lot_id),
                   detected_time
               )
               WHERE datetime(detected_time) > CURRENT_TIMESTAMP"""
        )
        connection.execute(
            """INSERT OR IGNORE INTO quality.defect_types(canonical_name)
               SELECT DISTINCT defect_type FROM quality.defect_records
               WHERE TRIM(defect_type) <> ''"""
        )
        connection.execute(
            """INSERT OR IGNORE INTO quality.defect_types(canonical_name)
               SELECT DISTINCT defect_type FROM knowledge.historical_cases
               WHERE TRIM(defect_type) <> ''"""
        )
        _seed_default_defect_types(connection, "quality")
        connection.execute(
            "INSERT INTO knowledge.knowledge_trigram_fts(knowledge_trigram_fts) VALUES ('rebuild')"
        )
        connection.execute(
            "INSERT INTO knowledge.case_trigram_fts(case_trigram_fts) VALUES ('rebuild')"
        )
        connection.commit()
        return counts
    finally:
        connection.close()


def ensure_department_databases() -> dict[str, int]:
    initialize()
    with db_session() as connection:
        has_manufacturing_data = bool(
            connection.execute("SELECT EXISTS(SELECT 1 FROM lots LIMIT 1)").fetchone()[
                0
            ]
        )
        companion_counts = {
            "equipment": connection.execute(
                "SELECT COUNT(*) FROM sensor_readings"
            ).fetchone()[0],
            "quality": connection.execute("SELECT COUNT(*) FROM wafer_maps").fetchone()[
                0
            ],
        }
    if not has_manufacturing_data:
        return migrate_legacy_database()
    missing = [
        department for department, count in companion_counts.items() if count == 0
    ]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            f"Department database set is incomplete: {names}. "
            "Restore the matching backup set before starting the application."
        )
    return {}


def validate_department_databases() -> dict[str, int | str]:
    """Run lightweight cross-department contract checks used by startup and tests."""
    with db_session() as connection:
        metadata = connection.execute(
            "SELECT end_date, forecast_start FROM simulation_metadata WHERE singleton_id = 1"
        ).fetchone()
        metadata_end_date = metadata["end_date"] if metadata else None
        metadata_forecast_start = metadata["forecast_start"] if metadata else None
        checks: dict[str, int | str] = {
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
            "sensor_orphans": connection.execute(
                "SELECT COUNT(*) FROM sensor_readings s LEFT JOIN lots l USING(lot_id) WHERE l.lot_id IS NULL"
            ).fetchone()[0],
            "defect_orphans": connection.execute(
                "SELECT COUNT(*) FROM defect_records d LEFT JOIN lots l USING(lot_id) WHERE l.lot_id IS NULL"
            ).fetchone()[0],
            "wafer_map_orphans": connection.execute(
                "SELECT COUNT(*) FROM wafer_maps w LEFT JOIN lots l USING(lot_id) WHERE l.lot_id IS NULL"
            ).fetchone()[0],
            "simulation_metadata_status": "present" if metadata else "missing",
            "simulation_end_date": metadata_end_date or "",
            "simulation_forecast_start": metadata_forecast_start or "",
            "uncatalogued_defects": connection.execute(
                """SELECT COUNT(DISTINCT d.defect_type) FROM defect_records d
                   LEFT JOIN defect_types t ON t.canonical_name = d.defect_type
                   WHERE t.defect_type_id IS NULL"""
            ).fetchone()[0],
            "knowledge_fts_delta": connection.execute(
                "SELECT ABS((SELECT COUNT(*) FROM knowledge_chunks) - "
                "(SELECT COUNT(*) FROM knowledge.knowledge_trigram_fts))"
            ).fetchone()[0],
            "case_fts_delta": connection.execute(
                "SELECT ABS((SELECT COUNT(*) FROM historical_cases) - "
                "(SELECT COUNT(*) FROM knowledge.case_trigram_fts))"
            ).fetchone()[0],
            "personal_knowledge_fts_delta": connection.execute(
                "SELECT ABS((SELECT COUNT(*) FROM personal_knowledge_chunks) - "
                "(SELECT COUNT(*) FROM knowledge.personal_knowledge_fts))"
            ).fetchone()[0],
        }
        for table, timestamp_column in (
            ("lots", "start_time"),
            ("process_runs", "run_time"),
            ("sensor_readings", "sample_time"),
            ("equipment_state_intervals", "start_time"),
            ("equipment_events", "event_time"),
            ("defect_records", "detected_time"),
            ("wafer_maps", "detected_time"),
        ):
            if metadata_end_date:
                checks[f"forecast_{table}"] = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE date({timestamp_column}) >= date(?) "
                    f"AND date({timestamp_column}) <= date(?)",
                    (metadata_forecast_start, metadata_end_date),
                ).fetchone()[0]
                checks[f"beyond_horizon_{table}"] = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE date({timestamp_column}) > date(?)",
                    (metadata_end_date,),
                ).fetchone()[0]
            else:
                checks[f"forecast_{table}"] = 0
                checks[f"beyond_horizon_{table}"] = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE date({timestamp_column}) > date('now')"
                ).fetchone()[0]
        # Keep this legacy manifest key while the declared horizon supersedes a wall-clock future check.
        checks["future_wafer_maps"] = checks["forecast_wafer_maps"]
    return checks


@contextmanager
def db_session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        yield connection
    finally:
        connection.close()


def get_active_defect_aliases(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Return active canonical defect names and their database-managed aliases."""
    with db_session(path) as connection:
        rows = connection.execute(
            """SELECT t.canonical_name, a.alias
               FROM defect_types t
               LEFT JOIN defect_type_aliases a ON a.defect_type_id = t.defect_type_id
               WHERE t.is_active = 1
               ORDER BY t.canonical_name, a.alias"""
        ).fetchall()
    aliases: dict[str, list[str]] = {}
    for row in rows:
        canonical_name = row["canonical_name"]
        aliases.setdefault(canonical_name, [canonical_name])
        if row["alias"] is not None:
            aliases[canonical_name].append(row["alias"])
    return {name: tuple(dict.fromkeys(values)) for name, values in aliases.items()}


def replace_defect_type_aliases(
    canonical_name: str, aliases: Iterable[str], path: Path | None = None
) -> None:
    """Create or update one active defect type and replace its aliases."""
    name = canonical_name.strip()
    if not name:
        raise ValueError("缺陷类型标准名称不能为空")
    cleaned_aliases = tuple(
        dict.fromkeys(alias.strip() for alias in aliases if alias.strip())
    )
    connection = connect(path)
    defect_types = writable_table("defect_types", path)
    defect_aliases = writable_table("defect_type_aliases", path)
    try:
        connection.execute(
            f"""INSERT INTO {defect_types}(canonical_name, is_active, updated_at)
               VALUES (?, 1, CURRENT_TIMESTAMP)
               ON CONFLICT(canonical_name) DO UPDATE SET
                   is_active = 1, updated_at = CURRENT_TIMESTAMP""",
            (name,),
        )
        defect_type_id = connection.execute(
            f"SELECT defect_type_id FROM {defect_types} WHERE canonical_name = ?",
            (name,),
        ).fetchone()[0]
        connection.execute(
            f"DELETE FROM {defect_aliases} WHERE defect_type_id = ?", (defect_type_id,)
        )
        connection.executemany(
            f"INSERT INTO {defect_aliases}(defect_type_id, alias) VALUES (?, ?)",
            ((defect_type_id, alias) for alias in cleaned_aliases),
        )
        connection.commit()
    finally:
        connection.close()
