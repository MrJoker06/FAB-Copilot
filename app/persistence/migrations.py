"""Application-owned state migrations; no demo generation or manufacturing tables."""

from __future__ import annotations

import json
import sqlite3
from ..core.model_capabilities import normalize_capabilities

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


MODEL_CAPABILITIES_SCHEMA_VERSION = 10


MODEL_COMPATIBILITY_SCHEMA_VERSION = 12


MODEL_HEALTH_SCHEMA_VERSION = 14


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
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(agent_tool_events)")
    }
    for name, definition in AGENT_TOOL_EVENT_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE agent_tool_events ADD COLUMN {name} {definition}"
            )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_tool_events_sequence "
        "ON agent_tool_events(run_id, sequence_no)"
    )


def _migrate_model_catalog_capabilities(connection: sqlite3.Connection) -> None:
    """Normalize catalog capability JSON without changing catalog columns or extensions."""
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "model_catalog" not in tables:
        return
    rows = connection.execute(
        "SELECT model_id, capabilities_json FROM model_catalog"
    ).fetchall()
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
        (MODEL_CAPABILITIES_SCHEMA_VERSION, "model catalog capabilities"),
    )


def _migrate_model_catalog_compatibility(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "model_catalog" not in tables:
        return
    columns = {row[1] for row in connection.execute("PRAGMA table_info(model_catalog)")}
    if "compatibility_json" not in columns:
        connection.execute(
            "ALTER TABLE model_catalog ADD COLUMN compatibility_json TEXT NOT NULL DEFAULT '{}'"
        )
    if "compatibility_checked_at" not in columns:
        connection.execute(
            "ALTER TABLE model_catalog ADD COLUMN compatibility_checked_at TEXT"
        )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, description TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (?, ?)",
        (MODEL_COMPATIBILITY_SCHEMA_VERSION, "model publication compatibility"),
    )


def _migrate_model_health(connection: sqlite3.Connection) -> None:
    """Add independent, passive model health state without changing publication data."""
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "model_catalog" not in tables:
        return
    connection.execute("""CREATE TABLE IF NOT EXISTS model_health (
        model_id TEXT PRIMARY KEY REFERENCES model_catalog(model_id) ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'unknown' CHECK(status IN ('unknown', 'healthy', 'degraded', 'open', 'half_open')),
        consecutive_failures INTEGER NOT NULL DEFAULT 0 CHECK(consecutive_failures >= 0),
        opened_at TEXT, open_until TEXT, recovery_claimed_at TEXT,
        last_success_at TEXT, last_failure_at TEXT, last_error_category TEXT,
        updated_at TEXT NOT NULL
    )""")
    connection.execute("""INSERT OR IGNORE INTO model_health(model_id, updated_at)
                       SELECT model_id, CURRENT_TIMESTAMP FROM model_catalog""")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, description TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, description) VALUES (?, ?)",
        (MODEL_HEALTH_SCHEMA_VERSION, "model circuit health"),
    )


def _migrate_personal_knowledge_tags_source(connection: sqlite3.Connection) -> None:
    """Add the RAG-023 provenance column without changing it on later starts."""
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'personal_knowledge_documents'"
        )
    }
    if "personal_knowledge_documents" not in tables:
        return
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(personal_knowledge_documents)")
    }
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


def migrate_knowledge(connection: sqlite3.Connection) -> None:
    _migrate_personal_knowledge_tags_source(connection)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(historical_cases)")
    }
    for name, definition in CASE_GOVERNANCE_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE historical_cases ADD COLUMN {name} {definition}"
            )


def migrate_agent(connection: sqlite3.Connection) -> None:
    for table, definitions in (
        ("chat_sessions", CHAT_SESSION_COLUMNS),
        ("chat_messages", CHAT_MESSAGE_COLUMNS),
    ):
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in definitions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                )
    _migrate_agent_runs(connection)
    _migrate_agent_tool_events(connection)
    _migrate_model_catalog_capabilities(connection)
    _migrate_model_catalog_compatibility(connection)
    _migrate_model_health(connection)
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_client_id ON chat_messages(session_id, client_message_id) WHERE role = 'user' AND client_message_id IS NOT NULL"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_sessions_owner_updated ON chat_sessions(tenant_id, owner_user_id, updated_at DESC)"
    )
