"""Schemas owned by the application; manufacturing fixtures live in demo_data."""

from __future__ import annotations

SCHEMA_VERSION = 15


SCHEMA_METADATA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description TEXT NOT NULL
);
"""


KNOWLEDGE_SCHEMA = (
    SCHEMA_METADATA
    + """
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

CREATE TABLE IF NOT EXISTS personal_knowledge_documents (
    document_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    checksum_sha256 TEXT NOT NULL,
    process_steps_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(process_steps_json)),
    equipment_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(equipment_ids_json)),
    effective_date TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(tags_json)),
    tags_source TEXT NOT NULL DEFAULT 'auto' CHECK(tags_source IN ('auto', 'user')),
    status TEXT NOT NULL CHECK(status IN ('uploaded', 'parsing', 'chunking', 'indexing', 'ready', 'failed', 'deleting')),
    storage_key TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(owner_user_id, checksum_sha256),
    UNIQUE(owner_user_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS personal_knowledge_chunks (
    chunk_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL REFERENCES personal_knowledge_documents(document_id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL,
    page_number INTEGER,
    section_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL CHECK(token_count >= 0),
    created_at TEXT NOT NULL,
    UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS personal_knowledge_jobs (
    job_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL CHECK(progress BETWEEN 0 AND 100),
    attempt INTEGER NOT NULL DEFAULT 1 CHECK(attempt > 0),
    error_code TEXT,
    error_message TEXT,
    retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS personal_knowledge_fts USING fts5(
    title, section_path, content,
    owner_user_id UNINDEXED, document_id UNINDEXED, chunk_id UNINDEXED,
    tokenize='trigram'
);

CREATE INDEX IF NOT EXISTS idx_personal_documents_owner_updated ON personal_knowledge_documents(owner_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_personal_documents_owner_status ON personal_knowledge_documents(owner_user_id, status);
CREATE INDEX IF NOT EXISTS idx_personal_chunks_document ON personal_knowledge_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_personal_chunks_owner ON personal_knowledge_chunks(owner_user_id, document_id);
CREATE INDEX IF NOT EXISTS idx_personal_jobs_owner_updated ON personal_knowledge_jobs(owner_user_id, updated_at DESC);
"""
)


AGENT_SCHEMA = (
    SCHEMA_METADATA
    + """
CREATE TABLE IF NOT EXISTS model_catalog (
    model_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_model TEXT NOT NULL,
    base_url TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('published', 'retired')),
    capabilities_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(capabilities_json)),
    compatibility_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(compatibility_json)),
    compatibility_checked_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS model_health (
    model_id TEXT PRIMARY KEY REFERENCES model_catalog(model_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'unknown' CHECK(status IN ('unknown', 'healthy', 'degraded', 'open', 'half_open')),
    consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
    opened_at TEXT,
    open_until TEXT,
    recovery_claimed_at TEXT,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_error_category TEXT,
    updated_at TEXT NOT NULL
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
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
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
    plan_step_id TEXT,
    started_at TEXT,
    completed_at TEXT,
    UNIQUE(run_id, sequence_no)
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
    required_evidence_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(required_evidence_json)),
    budget_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(budget_json)),
    missing_inputs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(missing_inputs_json)),
    clarification_questions_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(clarification_questions_json)),
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
    parameters_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(parameters_json)),
    parameter_sources_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(parameter_sources_json)),
    evidence_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(evidence_ids_json)),
    depends_on_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(depends_on_json)),
    required INTEGER NOT NULL DEFAULT 0 CHECK(required IN (0, 1)),
    success_criteria_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(success_criteria_json)),
    estimated_result_limit INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER,
    duration_ms REAL,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    PRIMARY KEY(run_id, step_id),
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
CREATE INDEX IF NOT EXISTS idx_model_catalog_status ON model_catalog(status, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_preferences_model ON user_model_preferences(model_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated ON chat_sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner_updated ON chat_sessions(tenant_id, owner_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_message ON agent_runs(assistant_message_id);
CREATE INDEX IF NOT EXISTS idx_tool_events_run ON agent_tool_events(run_id, sequence_no);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_tool_events_sequence ON agent_tool_events(run_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_execution_plans_status ON agent_execution_plans(execution_status, updated_at);
CREATE INDEX IF NOT EXISTS idx_plan_steps_run_status ON agent_plan_steps(run_id, status, sequence_no);
CREATE INDEX IF NOT EXISTS idx_message_sources_message ON message_sources(message_id);
"""
)


DEPARTMENT_SCHEMAS = {"knowledge": KNOWLEDGE_SCHEMA, "agent": AGENT_SCHEMA}

TABLE_DEPARTMENTS = {
    "knowledge_documents": "knowledge",
    "knowledge_chunks": "knowledge",
    "historical_cases": "knowledge",
    "personal_knowledge_documents": "knowledge",
    "personal_knowledge_chunks": "knowledge",
    "personal_knowledge_jobs": "knowledge",
    "model_catalog": "agent",
    "model_health": "agent",
    "user_model_preferences": "agent",
    "chat_sessions": "agent",
    "chat_messages": "agent",
    "agent_runs": "agent",
    "agent_tool_events": "agent",
    "agent_execution_plans": "agent",
    "agent_plan_steps": "agent",
    "message_sources": "agent",
}

MIGRATION_ORDER = tuple(TABLE_DEPARTMENTS)
