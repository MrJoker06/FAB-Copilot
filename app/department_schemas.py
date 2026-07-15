from __future__ import annotations


SCHEMA_VERSION = 2

SCHEMA_METADATA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description TEXT NOT NULL
);
"""


MANUFACTURING_SCHEMA = SCHEMA_METADATA + """
CREATE TABLE IF NOT EXISTS lots (
    lot_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    technology_nm INTEGER NOT NULL CHECK(technology_nm > 0),
    route TEXT NOT NULL,
    priority TEXT NOT NULL,
    start_time TEXT NOT NULL,
    complete_time TEXT,
    status TEXT NOT NULL,
    wafer_count INTEGER NOT NULL CHECK(wafer_count > 0),
    good_wafers INTEGER NOT NULL CHECK(good_wafers BETWEEN 0 AND wafer_count),
    yield_rate REAL NOT NULL CHECK(yield_rate BETWEEN 0 AND 1),
    cycle_time_hours REAL NOT NULL CHECK(cycle_time_hours >= 0),
    hold_hours REAL NOT NULL CHECK(hold_hours >= 0)
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
    duration_sec REAL NOT NULL CHECK(duration_sec >= 0),
    thickness_nm REAL,
    uniformity_pct REAL,
    defect_density REAL NOT NULL CHECK(defect_density >= 0),
    measurement_name TEXT NOT NULL DEFAULT 'Defect density',
    measurement_value REAL,
    measurement_unit TEXT NOT NULL DEFAULT '',
    spec_lsl REAL,
    spec_usl REAL,
    pass_flag INTEGER NOT NULL CHECK(pass_flag IN (0, 1)),
    excursion_code TEXT,
    operation_seq INTEGER NOT NULL DEFAULT 1 CHECK(operation_seq > 0),
    layer_name TEXT NOT NULL DEFAULT 'BASE',
    queue_hours REAL NOT NULL DEFAULT 0 CHECK(queue_hours >= 0),
    rework_flag INTEGER NOT NULL DEFAULT 0 CHECK(rework_flag IN (0, 1)),
    scenario_id TEXT,
    CHECK(spec_lsl IS NULL OR spec_usl IS NULL OR spec_lsl < spec_usl),
    UNIQUE(lot_id, operation_seq)
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
    visible_to_agent INTEGER NOT NULL DEFAULT 0 CHECK(visible_to_agent IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_lots_complete ON lots(complete_time);
CREATE INDEX IF NOT EXISTS idx_runs_time ON process_runs(run_time);
CREATE INDEX IF NOT EXISTS idx_runs_equipment ON process_runs(equipment_id, run_time);
CREATE INDEX IF NOT EXISTS idx_runs_lot_step ON process_runs(lot_id, process_step, run_time DESC);
CREATE INDEX IF NOT EXISTS idx_runs_step_time ON process_runs(process_step, run_time);
"""


EQUIPMENT_SCHEMA = SCHEMA_METADATA + """
CREATE TABLE IF NOT EXISTS sensor_readings (
    reading_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id TEXT NOT NULL,
    operation_seq INTEGER NOT NULL CHECK(operation_seq > 0),
    process_step TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    chamber TEXT NOT NULL,
    sample_time TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    signal_value REAL,
    signal_unit TEXT NOT NULL,
    is_missing INTEGER NOT NULL DEFAULT 0 CHECK(is_missing IN (0, 1)),
    is_outlier INTEGER NOT NULL DEFAULT 0 CHECK(is_outlier IN (0, 1)),
    CHECK((is_missing = 1 AND signal_value IS NULL) OR (is_missing = 0 AND signal_value IS NOT NULL)),
    UNIQUE(lot_id, operation_seq, signal_name, sample_time)
);

CREATE TABLE IF NOT EXISTS equipment_state_intervals (
    state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,
    chamber TEXT NOT NULL,
    start_time TEXT NOT NULL,
    duration_minutes REAL NOT NULL CHECK(duration_minutes >= 0),
    semi_e10_state TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS equipment_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id TEXT NOT NULL,
    event_time TEXT NOT NULL,
    event_type TEXT NOT NULL,
    duration_minutes REAL NOT NULL CHECK(duration_minutes >= 0),
    severity TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sensor_equipment_time ON sensor_readings(equipment_id, sample_time);
CREATE INDEX IF NOT EXISTS idx_sensor_signal_time ON sensor_readings(signal_name, sample_time);
CREATE INDEX IF NOT EXISTS idx_sensor_step_time ON sensor_readings(process_step, sample_time);
CREATE INDEX IF NOT EXISTS idx_sensor_lot ON sensor_readings(lot_id, operation_seq);
CREATE INDEX IF NOT EXISTS idx_states_equipment_time ON equipment_state_intervals(equipment_id, start_time);
CREATE INDEX IF NOT EXISTS idx_events_time ON equipment_events(event_time);
"""


QUALITY_SCHEMA = SCHEMA_METADATA + """
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

CREATE TABLE IF NOT EXISTS defect_records (
    defect_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id TEXT NOT NULL,
    detected_time TEXT NOT NULL,
    process_step TEXT NOT NULL,
    defect_type TEXT NOT NULL,
    count INTEGER NOT NULL CHECK(count >= 0),
    disposition TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wafer_maps (
    wafer_map_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id TEXT NOT NULL,
    wafer_no INTEGER NOT NULL CHECK(wafer_no > 0),
    detected_time TEXT NOT NULL,
    process_step TEXT NOT NULL,
    equipment_id TEXT NOT NULL,
    pattern_class TEXT NOT NULL,
    tested_dies INTEGER NOT NULL CHECK(tested_dies >= 0),
    failed_dies INTEGER NOT NULL CHECK(failed_dies BETWEEN 0 AND tested_dies),
    map_seed INTEGER NOT NULL,
    UNIQUE(lot_id, wafer_no)
);

CREATE INDEX IF NOT EXISTS idx_defects_time ON defect_records(detected_time);
CREATE INDEX IF NOT EXISTS idx_defects_lot ON defect_records(lot_id, detected_time);
CREATE INDEX IF NOT EXISTS idx_defects_type_time ON defect_records(defect_type, detected_time);
CREATE INDEX IF NOT EXISTS idx_defect_aliases_type ON defect_type_aliases(defect_type_id);
CREATE INDEX IF NOT EXISTS idx_wafer_maps_pattern ON wafer_maps(pattern_class, detected_time);
CREATE INDEX IF NOT EXISTS idx_wafer_maps_lot ON wafer_maps(lot_id);
"""


KNOWLEDGE_SCHEMA = SCHEMA_METADATA + """
CREATE TABLE IF NOT EXISTS knowledge_documents (
    source TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    owner TEXT NOT NULL,
    authority INTEGER NOT NULL CHECK(authority BETWEEN 1 AND 5),
    process_steps TEXT NOT NULL,
    equipment_families TEXT NOT NULL,
    tags TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source TEXT NOT NULL REFERENCES knowledge_documents(source) ON DELETE CASCADE,
    section TEXT NOT NULL,
    content TEXT NOT NULL
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
    root_cause_confidence REAL NOT NULL DEFAULT 0 CHECK(root_cause_confidence BETWEEN 0 AND 1),
    validation_method TEXT NOT NULL DEFAULT '',
    recurrence_status TEXT NOT NULL DEFAULT 'Unknown',
    approved_by TEXT NOT NULL DEFAULT '',
    case_status TEXT NOT NULL DEFAULT 'Draft'
);

CREATE VIRTUAL TABLE IF NOT EXISTS case_trigram_fts USING fts5(
    title, process_step, equipment_id, problem, solution, result, summary, tags,
    content='historical_cases', content_rowid='rowid', tokenize='trigram'
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source ON knowledge_chunks(source, chunk_id);
CREATE INDEX IF NOT EXISTS idx_cases_step_date ON historical_cases(process_step, occurred_date);
CREATE INDEX IF NOT EXISTS idx_cases_governance ON historical_cases(case_status, process_step, defect_type);
"""


AGENT_SCHEMA = SCHEMA_METADATA + """
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
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
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
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS agent_tool_events (
    tool_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(arguments_json)),
    status TEXT NOT NULL,
    row_count INTEGER,
    duration_ms REAL,
    error_message TEXT,
    UNIQUE(run_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS message_sources (
    source_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES chat_messages(message_id) ON DELETE CASCADE,
    reference_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    title TEXT NOT NULL,
    section TEXT NOT NULL,
    UNIQUE(message_id, reference_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, message_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_message ON agent_runs(assistant_message_id);
CREATE INDEX IF NOT EXISTS idx_tool_events_run ON agent_tool_events(run_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_message_sources_message ON message_sources(message_id);
"""


DEPARTMENT_SCHEMAS = {
    "main": MANUFACTURING_SCHEMA,
    "equipment": EQUIPMENT_SCHEMA,
    "quality": QUALITY_SCHEMA,
    "knowledge": KNOWLEDGE_SCHEMA,
    "agent": AGENT_SCHEMA,
}

TABLE_DEPARTMENTS = {
    "lots": "main",
    "process_runs": "main",
    "simulation_scenarios": "main",
    "sensor_readings": "equipment",
    "equipment_state_intervals": "equipment",
    "equipment_events": "equipment",
    "defect_types": "quality",
    "defect_type_aliases": "quality",
    "defect_records": "quality",
    "wafer_maps": "quality",
    "knowledge_documents": "knowledge",
    "knowledge_chunks": "knowledge",
    "historical_cases": "knowledge",
    "chat_sessions": "agent",
    "chat_messages": "agent",
    "agent_runs": "agent",
    "agent_tool_events": "agent",
    "message_sources": "agent",
}

MIGRATION_ORDER = tuple(TABLE_DEPARTMENTS)
