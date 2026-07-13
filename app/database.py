from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import get_settings


SCHEMA = """
PRAGMA journal_mode=WAL;
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

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
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
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    assistant_message_id INTEGER REFERENCES chat_messages(message_id) ON DELETE SET NULL,
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
    error_message TEXT
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
CREATE INDEX IF NOT EXISTS idx_defects_time ON defect_records(detected_time);
CREATE INDEX IF NOT EXISTS idx_events_time ON equipment_events(event_time);
CREATE INDEX IF NOT EXISTS idx_sensor_equipment_time ON sensor_readings(equipment_id, sample_time);
CREATE INDEX IF NOT EXISTS idx_sensor_signal_time ON sensor_readings(signal_name, sample_time);
CREATE INDEX IF NOT EXISTS idx_states_equipment_time ON equipment_state_intervals(equipment_id, start_time);
CREATE INDEX IF NOT EXISTS idx_wafer_maps_pattern ON wafer_maps(pattern_class, detected_time);
CREATE INDEX IF NOT EXISTS idx_cases_step_date ON historical_cases(process_step, occurred_date);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, message_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_tool_events_run ON agent_tool_events(run_id, sequence_no);
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
    "model": "TEXT NOT NULL DEFAULT ''",
    "archived_at": "TEXT",
    "last_message_preview": "TEXT NOT NULL DEFAULT ''",
}


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or get_settings().database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize(path: Path | None = None) -> None:
    connection = connect(path)
    try:
        connection.executescript(SCHEMA)
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
        connection.execute("CREATE INDEX IF NOT EXISTS idx_cases_governance ON historical_cases(case_status, process_step, defect_type)")
        connection.commit()
    finally:
        connection.close()


@contextmanager
def db_session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        yield connection
    finally:
        connection.close()


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]
