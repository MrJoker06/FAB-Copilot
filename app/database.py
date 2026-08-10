from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .config import get_settings
from .department_schemas import (
    DEPARTMENT_SCHEMAS,
    MIGRATION_ORDER,
    SCHEMA_VERSION,
    TABLE_DEPARTMENTS,
)


SCHEMA = """
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS lots (
    lot_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    technology_nm INTEGER NOT NULL,
    route TEXT NOT NULL,
    priority TEXT NOT NULL,
    start_time TEXT NOT NULL,
    complete_time TEXT,
    status TEXT NOT NULL,
    wafer_count INTEGER NOT NULL,
    good_wafers INTEGER NOT NULL,
    yield_rate REAL NOT NULL,
    cycle_time_hours REAL NOT NULL,
    hold_hours REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS process_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id TEXT NOT NULL REFERENCES lots(lot_id),
    process_step TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    chamber TEXT NOT NULL,
    recipe TEXT NOT NULL,
    run_time TEXT NOT NULL,
    temperature_c REAL NOT NULL,
    pressure_torr REAL NOT NULL,
    duration_sec REAL NOT NULL,
    thickness_nm REAL,
    uniformity_pct REAL,
    defect_density REAL NOT NULL,
    measurement_name TEXT NOT NULL DEFAULT 'Defect density',
    measurement_value REAL,
    measurement_unit TEXT NOT NULL DEFAULT '',
    spec_lsl REAL,
    spec_usl REAL,
    pass_flag INTEGER NOT NULL,
    excursion_code TEXT
);

CREATE TABLE IF NOT EXISTS sensor_readings (
    reading_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id TEXT NOT NULL REFERENCES lots(lot_id),
    operation_seq INTEGER NOT NULL,
    process_step TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    chamber TEXT NOT NULL,
    sample_time TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    signal_value REAL,
    signal_unit TEXT NOT NULL,
    is_missing INTEGER NOT NULL DEFAULT 0,
    is_outlier INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS equipment_state_intervals (
    state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,
    chamber TEXT NOT NULL,
    start_time TEXT NOT NULL,
    duration_minutes REAL NOT NULL,
    semi_e10_state TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wafer_maps (
    wafer_map_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id TEXT NOT NULL REFERENCES lots(lot_id),
    wafer_no INTEGER NOT NULL,
    detected_time TEXT NOT NULL,
    process_step TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    pattern_class TEXT NOT NULL,
    tested_dies INTEGER NOT NULL,
    failed_dies INTEGER NOT NULL,
    map_seed INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS simulation_scenarios (
    scenario_id TEXT PRIMARY KEY,
    process_step TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    scenario_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    observable_signals TEXT NOT NULL,
    source_profile TEXT NOT NULL,
    visible_to_agent INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS equipment_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    event_type TEXT NOT NULL,
    duration_minutes REAL NOT NULL,
    severity TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS defect_records (
    defect_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id TEXT NOT NULL REFERENCES lots(lot_id),
    detected_time TEXT NOT NULL,
    process_step TEXT NOT NULL,
    defect_type TEXT NOT NULL,
    count INTEGER NOT NULL,
    disposition TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS defect_types (
    defect_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS defect_type_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    defect_type_id INTEGER NOT NULL REFERENCES defect_types(defect_type_id) ON DELETE CASCADE,
    alias TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    section TEXT NOT NULL,
    content TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    source TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    owner TEXT NOT NULL,
    authority INTEGER NOT NULL,
    process_steps TEXT NOT NULL,
    equipment_families TEXT NOT NULL,
    tags TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_trigram_fts USING fts5(
    title, section, content, content='knowledge_chunks', content_rowid='chunk_id',
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS historical_cases (
    case_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    process_step TEXT NOT NULL,
    equipment_id TEXT,
    occurred_date TEXT NOT NULL,
    severity TEXT NOT NULL,
    problem TEXT NOT NULL,
    solution TEXT NOT NULL,
    result TEXT NOT NULL,
    summary TEXT NOT NULL,
    tags TEXT NOT NULL,
    equipment_family TEXT NOT NULL DEFAULT '',
    defect_type TEXT NOT NULL DEFAULT '',
    symptoms TEXT NOT NULL DEFAULT '',
    root_cause TEXT NOT NULL DEFAULT '',
    root_cause_confidence REAL NOT NULL DEFAULT 0,
    validation_method TEXT NOT NULL DEFAULT '',
    recurrence_status TEXT NOT NULL DEFAULT 'Unknown',
    approved_by TEXT NOT NULL DEFAULT '',
    case_status TEXT NOT NULL DEFAULT 'Draft'
);

CREATE VIRTUAL TABLE IF NOT EXISTS case_trigram_fts USING fts5(
    title, process_step, equipment_id, problem, solution, result, summary, tags,
    content='historical_cases', content_rowid='rowid',
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS model_catalog (
    model_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_model TEXT NOT NULL,
    base_url TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('published', 'retired')),
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS user_model_preferences (
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    model_id TEXT NOT NULL REFERENCES model_catalog(model_id),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'demo-fab',
    owner_user_id TEXT NOT NULL DEFAULT 'local-user',
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    archived_at TEXT,
    last_message_preview TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    client_message_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    user_message_id INTEGER REFERENCES chat_messages(message_id) ON DELETE SET NULL,
    assistant_message_id INTEGER REFERENCES chat_messages(message_id) ON DELETE SET NULL,
    question_preview TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    first_token_ms REAL,
    duration_ms REAL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS agent_tool_events (
    tool_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    row_count INTEGER,
    duration_ms REAL,
    error_message TEXT,
    plan_step_id TEXT,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_execution_plans (
    run_id TEXT PRIMARY KEY REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    planner_version TEXT NOT NULL,
    definition_status TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    route_intent TEXT NOT NULL DEFAULT 'unknown',
    playbook_id TEXT,
    playbook_version TEXT,
    required_evidence_json TEXT NOT NULL DEFAULT '[]',
    budget_json TEXT NOT NULL DEFAULT '{}',
    missing_inputs_json TEXT NOT NULL DEFAULT '[]',
    clarification_questions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    interruption_reason TEXT
);

CREATE TABLE IF NOT EXISTS agent_plan_steps (
    run_id TEXT NOT NULL REFERENCES agent_execution_plans(run_id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    title TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    parameter_sources_json TEXT NOT NULL DEFAULT '{}',
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    required INTEGER NOT NULL DEFAULT 0,
    success_criteria_json TEXT NOT NULL DEFAULT '[]',
    estimated_result_limit INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER,
    duration_ms REAL,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    PRIMARY KEY(run_id, step_id)
);

CREATE TABLE IF NOT EXISTS message_sources (
    source_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES chat_messages(message_id) ON DELETE CASCADE,
    reference_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    title TEXT NOT NULL,
    section TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lots_complete ON lots(complete_time);
CREATE INDEX IF NOT EXISTS idx_runs_time ON process_runs(run_time);
CREATE INDEX IF NOT EXISTS idx_runs_equipment ON process_runs(equipment_id, run_time);
CREATE INDEX IF NOT EXISTS idx_runs_lot_step ON process_runs(lot_id, process_step, run_time DESC);
CREATE INDEX IF NOT EXISTS idx_runs_step_time ON process_runs(process_step, run_time);
CREATE INDEX IF NOT EXISTS idx_defects_time ON defect_records(detected_time);
CREATE INDEX IF NOT EXISTS idx_defect_aliases_type ON defect_type_aliases(defect_type_id);
CREATE INDEX IF NOT EXISTS idx_events_time ON equipment_events(event_time);
CREATE INDEX IF NOT EXISTS idx_sensor_equipment_time ON sensor_readings(equipment_id, sample_time);
CREATE INDEX IF NOT EXISTS idx_sensor_signal_time ON sensor_readings(signal_name, sample_time);
CREATE INDEX IF NOT EXISTS idx_states_equipment_time ON equipment_state_intervals(equipment_id, start_time);
CREATE INDEX IF NOT EXISTS idx_wafer_maps_pattern ON wafer_maps(pattern_class, detected_time);
CREATE INDEX IF NOT EXISTS idx_cases_step_date ON historical_cases(process_step, occurred_date);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, message_id);
CREATE INDEX IF NOT EXISTS idx_model_catalog_status ON model_catalog(status, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_preferences_model ON user_model_preferences(model_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner_updated ON chat_sessions(tenant_id, owner_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_events_run ON agent_tool_events(run_id, sequence_no);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_tool_events_sequence ON agent_tool_events(run_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_execution_plans_status ON agent_execution_plans(execution_status, updated_at);
CREATE INDEX IF NOT EXISTS idx_plan_steps_run_status ON agent_plan_steps(run_id, status, sequence_no);
CREATE INDEX IF NOT EXISTS idx_message_sources_message ON message_sources(message_id);
"""


CASE_GOVERNANCE_COLUMNS = {
    "equipment_family": "TEXT NOT NULL DEFAULT ''",
    "defect_type": "TEXT NOT NULL DEFAULT ''",
    "symptoms": "TEXT NOT NULL DEFAULT ''",
    "root_cause": "TEXT NOT NULL DEFAULT ''",
    "root_cause_confidence": "REAL NOT NULL DEFAULT 0",
    "validation_method": "TEXT NOT NULL DEFAULT ''",
    "recurrence_status": "TEXT NOT NULL DEFAULT 'Unknown'",
    "approved_by": "TEXT NOT NULL DEFAULT ''",
    "case_status": "TEXT NOT NULL DEFAULT 'Draft'",
}

PROCESS_RUN_MEASUREMENT_COLUMNS = {
    "operation_seq": "INTEGER NOT NULL DEFAULT 1",
    "layer_name": "TEXT NOT NULL DEFAULT 'BASE'",
    "queue_hours": "REAL NOT NULL DEFAULT 0",
    "rework_flag": "INTEGER NOT NULL DEFAULT 0",
    "scenario_id": "TEXT",
    "measurement_name": "TEXT NOT NULL DEFAULT 'Defect density'",
    "measurement_value": "REAL",
    "measurement_unit": "TEXT NOT NULL DEFAULT ''",
    "spec_lsl": "REAL",
    "spec_usl": "REAL",
}

CHAT_SESSION_COLUMNS = {
    "tenant_id": "TEXT NOT NULL DEFAULT 'demo-fab'",
    "owner_user_id": "TEXT NOT NULL DEFAULT 'local-user'",
    "model": "TEXT NOT NULL DEFAULT ''",
    "archived_at": "TEXT",
    "last_message_preview": "TEXT NOT NULL DEFAULT ''",
}

CHAT_MESSAGE_COLUMNS = {
    "client_message_id": "TEXT",
}

AGENT_RUN_COLUMNS = {
    "user_message_id": "INTEGER REFERENCES chat_messages(message_id) ON DELETE SET NULL",
    "question_preview": "TEXT NOT NULL DEFAULT ''",
}

AGENT_TOOL_EVENT_COLUMNS = {
    "plan_step_id": "TEXT",
    "started_at": "TEXT",
    "completed_at": "TEXT",
}


def _migrate_agent_runs(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")}
    for name, definition in AGENT_RUN_COLUMNS.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE agent_runs ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_user_message ON agent_runs(user_message_id)"
    )
    connection.execute(
        """UPDATE agent_runs
           SET user_message_id = (
               SELECT m.message_id FROM chat_messages m
               WHERE m.session_id = agent_runs.session_id AND m.role = 'user'
                 AND (agent_runs.assistant_message_id IS NULL OR m.message_id < agent_runs.assistant_message_id)
               ORDER BY m.message_id DESC LIMIT 1
           )
           WHERE user_message_id IS NULL"""
    )
    connection.execute(
        """UPDATE agent_runs
           SET question_preview = COALESCE((
               SELECT substr(trim(replace(replace(m.content, char(10), ' '), char(13), ' ')), 1, 240)
               FROM chat_messages m WHERE m.message_id = agent_runs.user_message_id
           ), '')
           WHERE question_preview = ''"""
    )


def _migrate_agent_tool_events(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_tool_events)")}
    for name, definition in AGENT_TOOL_EVENT_COLUMNS.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE agent_tool_events ADD COLUMN {name} {definition}")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_tool_events_sequence "
        "ON agent_tool_events(run_id, sequence_no)"
    )


def _migrate_model_catalog_capabilities(connection: sqlite3.Connection) -> None:
    """Normalize catalog capability JSON without changing catalog columns or extensions."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "model_catalog" not in tables:
        return
    from .model_registry import normalize_capabilities

    rows = connection.execute("SELECT model_id, capabilities_json FROM model_catalog").fetchall()
    for row in rows:
        try:
            parsed = json.loads(row[1] or "{}")
        except (TypeError, json.JSONDecodeError):
            parsed = {}
        normalized = normalize_capabilities(parsed)
        encoded = json.dumps(normalized, separators=(",", ":"))
        if encoded != (row[1] or ""):
            connection.execute(
                "UPDATE model_catalog SET capabilities_json = ? WHERE model_id = ?",
                (encoded, row[0]),
            )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, description TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (?, ?)",
        (SCHEMA_VERSION, "model catalog capabilities"),
    )


# Bootstrap data for a fresh database. Runtime matching reads the database tables,
# so operators can add or change types without changing application code.
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


def _seed_default_defect_types(connection: sqlite3.Connection, schema: str = "") -> None:
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


def _connect_single(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=20000")
    return connection


def sqlite_journal_mode(path: Path) -> str:
    configured = os.getenv("FAB_SQLITE_JOURNAL_MODE", "auto").strip().upper()
    if configured in {"DELETE", "WAL", "TRUNCATE", "PERSIST"}:
        return configured
    if configured != "AUTO":
        raise ValueError("FAB_SQLITE_JOURNAL_MODE 必须是 auto、DELETE、WAL、TRUNCATE 或 PERSIST")
    return "DELETE" if path.absolute().as_posix().startswith("/mnt/") else "WAL"


def _initialize_legacy(path: Path) -> None:
    connection = _connect_single(path)
    try:
        connection.execute(f"PRAGMA journal_mode={sqlite_journal_mode(path)}")
        connection.executescript(SCHEMA)
        _migrate_personal_knowledge_tags_source(connection)
        existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(historical_cases)")}
        for name, definition in CASE_GOVERNANCE_COLUMNS.items():
            if name not in existing_columns:
                connection.execute(f"ALTER TABLE historical_cases ADD COLUMN {name} {definition}")
        run_columns = {row[1] for row in connection.execute("PRAGMA table_info(process_runs)")}
        for name, definition in PROCESS_RUN_MEASUREMENT_COLUMNS.items():
            if name not in run_columns:
                connection.execute(f"ALTER TABLE process_runs ADD COLUMN {name} {definition}")
        session_columns = {row[1] for row in connection.execute("PRAGMA table_info(chat_sessions)")}
        for name, definition in CHAT_SESSION_COLUMNS.items():
            if name not in session_columns:
                connection.execute(f"ALTER TABLE chat_sessions ADD COLUMN {name} {definition}")
        message_columns = {row[1] for row in connection.execute("PRAGMA table_info(chat_messages)")}
        for name, definition in CHAT_MESSAGE_COLUMNS.items():
            if name not in message_columns:
                connection.execute(f"ALTER TABLE chat_messages ADD COLUMN {name} {definition}")
        _migrate_agent_runs(connection)
        _migrate_agent_tool_events(connection)
        _migrate_model_catalog_capabilities(connection)
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_client_id "
            "ON chat_messages(session_id, client_message_id) "
            "WHERE role = 'user' AND client_message_id IS NOT NULL"
        )
        _seed_default_defect_types(connection)
        connection.execute("CREATE INDEX IF NOT EXISTS idx_cases_governance ON historical_cases(case_status, process_step, defect_type)")
        connection.commit()
    finally:
        connection.close()


def _initialize_departments() -> None:
    paths = department_paths()
    for department, path in paths.items():
        connection = _connect_single(path)
        try:
            connection.execute(f"PRAGMA journal_mode={sqlite_journal_mode(path)}")
            connection.executescript(DEPARTMENT_SCHEMAS[department])
            if department == "knowledge":
                _migrate_personal_knowledge_tags_source(connection)
            if department == "agent":
                session_columns = {row[1] for row in connection.execute("PRAGMA table_info(chat_sessions)")}
                for name, definition in CHAT_SESSION_COLUMNS.items():
                    if name not in session_columns:
                        connection.execute(f"ALTER TABLE chat_sessions ADD COLUMN {name} {definition}")
                message_columns = {row[1] for row in connection.execute("PRAGMA table_info(chat_messages)")}
                for name, definition in CHAT_MESSAGE_COLUMNS.items():
                    if name not in message_columns:
                        connection.execute(f"ALTER TABLE chat_messages ADD COLUMN {name} {definition}")
                _migrate_agent_runs(connection)
                _migrate_agent_tool_events(connection)
                _migrate_model_catalog_capabilities(connection)
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_client_id "
                    "ON chat_messages(session_id, client_message_id) "
                    "WHERE role = 'user' AND client_message_id IS NOT NULL"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner_updated "
                    "ON chat_sessions(tenant_id, owner_user_id, updated_at DESC)"
                )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (?, ?)",
                (SCHEMA_VERSION, f"department schema: {department}"),
            )
            if department == "quality":
                _seed_default_defect_types(connection)
            connection.commit()
        finally:
            connection.close()


def _migrate_personal_knowledge_tags_source(connection: sqlite3.Connection) -> None:
    """Add the RAG-023 provenance column without changing it on later starts."""
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'personal_knowledge_documents'"
        )
    }
    if "personal_knowledge_documents" not in tables:
        return
    columns = {row[1] for row in connection.execute("PRAGMA table_info(personal_knowledge_documents)")}
    if "tags_source" in columns:
        return
    connection.execute(
        "ALTER TABLE personal_knowledge_documents ADD COLUMN tags_source TEXT NOT NULL "
        "DEFAULT 'auto' CHECK(tags_source IN ('auto', 'user'))"
    )
    # This runs only while adding the column: legacy non-empty choices were human input.
    connection.execute(
        "UPDATE personal_knowledge_documents SET tags_source = 'user' "
        "WHERE json_array_length(tags_json) > 0"
    )


def connect(path: Path | None = None) -> sqlite3.Connection:
    if path is not None:
        return _connect_single(path)
    paths = department_paths()
    if any(not item.exists() for item in paths.values()):
        _initialize_departments()
    connection = _connect_single(paths["main"])
    for department in ("equipment", "quality", "knowledge", "agent"):
        connection.execute(f"ATTACH DATABASE ? AS {department}", (str(paths[department]),))
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


def migrate_legacy_database(source: Path | None = None, force: bool = False) -> dict[str, int]:
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
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
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
                row[1] for row in connection.execute(f"PRAGMA main.table_info('{table}')")
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
            connection.execute("SELECT EXISTS(SELECT 1 FROM lots LIMIT 1)").fetchone()[0]
        )
        companion_counts = {
            "equipment": connection.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0],
            "quality": connection.execute("SELECT COUNT(*) FROM wafer_maps").fetchone()[0],
        }
    if not has_manufacturing_data:
        return migrate_legacy_database()
    missing = [department for department, count in companion_counts.items() if count == 0]
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
            "future_wafer_maps": connection.execute(
                "SELECT COUNT(*) FROM wafer_maps WHERE datetime(detected_time) > CURRENT_TIMESTAMP"
            ).fetchone()[0],
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
    return checks


@contextmanager
def db_session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        yield connection
    finally:
        connection.close()


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


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
    cleaned_aliases = tuple(dict.fromkeys(alias.strip() for alias in aliases if alias.strip()))
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
            f"SELECT defect_type_id FROM {defect_types} WHERE canonical_name = ?", (name,)
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
