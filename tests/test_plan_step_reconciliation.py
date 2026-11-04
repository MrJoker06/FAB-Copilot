from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app.persistence import execution_store

SCHEMA = """
CREATE TABLE agent.agent_execution_plans (
    run_id TEXT PRIMARY KEY,
    execution_status TEXT,
    updated_at TEXT
);
CREATE TABLE agent.agent_plan_steps (
    run_id TEXT,
    step_id TEXT,
    sequence_no INTEGER,
    title TEXT,
    tool_name TEXT,
    parameters_json TEXT,
    parameter_sources_json TEXT,
    evidence_ids_json TEXT,
    depends_on_json TEXT,
    required INTEGER DEFAULT 0,
    success_criteria_json TEXT,
    estimated_result_limit INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    attempt_count INTEGER DEFAULT 0,
    row_count INTEGER,
    duration_ms REAL,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT
);
CREATE TABLE agent.agent_tool_events (
    tool_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    sequence_no INTEGER,
    tool_name TEXT,
    arguments_json TEXT,
    status TEXT,
    row_count INTEGER,
    duration_ms REAL,
    error_message TEXT,
    plan_step_id TEXT,
    started_at TEXT,
    completed_at TEXT
);
"""


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ':memory:' AS agent")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def _patched_session(conn):
    @contextmanager
    def session():
        yield conn

    with patch.object(execution_store, "db_session", session):
        yield


def _add_step(conn, run_id, step_id, tool, tool_parameters, status="pending"):
    conn.execute(
        """INSERT INTO agent.agent_plan_steps(
               run_id, step_id, sequence_no, title, tool_name, parameters_json, status
           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, step_id, int(step_id[1:]), tool, tool, json_params(tool_parameters), status),
    )


def json_params(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class PlanStepReconciliationTests(unittest.TestCase):
    def test_trace_marks_matching_steps_as_succeeded_even_after_finalize(self):
        conn = _connection()
        self.addCleanup(conn.close)
        conn.execute(
            "INSERT INTO agent.agent_execution_plans(run_id, execution_status) VALUES ('r1', 'running')"
        )
        _add_step(conn, "r1", "S01", "get_fab_overview", {"start": "2026-01-01"})
        _add_step(conn, "r1", "S02", "get_yield_trend", {"start": "2026-01-01"}, status="skipped")

        trace = [
            {"tool": "get_fab_overview", "arguments": {"start": "2026-01-01"}, "status": "ok", "rows": 1},
            {"tool": "get_yield_trend", "arguments": {"start": "2026-01-01"}, "status": "error", "rows": None,
             "error": "boom"},
        ]
        with _patched_session(conn):
            updated = execution_store.reconcile_plan_steps("r1", trace)

        self.assertEqual(updated, 2)
        statuses = {
            row["step_id"]: row
            for row in conn.execute(
                "SELECT step_id, status, row_count, error_message FROM agent.agent_plan_steps WHERE run_id='r1'"
            )
        }
        self.assertEqual(statuses["S01"]["status"], "succeeded")
        self.assertEqual(statuses["S01"]["row_count"], 1)
        self.assertEqual(statuses["S02"]["status"], "failed")
        self.assertEqual(statuses["S02"]["error_message"], "boom")

    def test_empty_arguments_still_match_the_planned_step(self):
        conn = _connection()
        self.addCleanup(conn.close)
        conn.execute(
            "INSERT INTO agent.agent_execution_plans(run_id, execution_status) VALUES ('r4', 'running')"
        )
        _add_step(conn, "r4", "S01", "get_sensor_summary", {"start": "2026-01-01", "end": "2026-02-01"})

        trace = [{"tool": "get_sensor_summary", "arguments": {}, "status": "ok", "rows": 4}]
        with _patched_session(conn):
            updated = execution_store.reconcile_plan_steps("r4", trace)

        self.assertEqual(updated, 1)
        step = conn.execute(
            "SELECT status, row_count FROM agent.agent_plan_steps WHERE run_id='r4'"
        ).fetchone()
        self.assertEqual(step["status"], "succeeded")
        self.assertEqual(step["row_count"], 4)

    def test_reconcile_reuses_the_callers_connection(self):
        conn = _connection()
        self.addCleanup(conn.close)
        conn.execute(
            "INSERT INTO agent.agent_execution_plans(run_id, execution_status) VALUES ('r5', 'running')"
        )
        _add_step(conn, "r5", "S01", "get_fab_overview", {"start": "2026-01-01"})

        # No patched session: passing a connection must not open a second session.
        updated = execution_store.reconcile_plan_steps(
            "r5",
            [{"tool": "get_fab_overview", "arguments": {"start": "2026-01-01"}, "status": "ok"}],
            connection=conn,
        )
        self.assertEqual(updated, 1)
    def test_unmatched_trace_items_leave_steps_pending(self):
        conn = _connection()
        self.addCleanup(conn.close)
        _add_step(conn, "r2", "S01", "get_fab_overview", {"start": "2026-01-01"})

        trace = [{"tool": "get_recent_excursions", "arguments": {}, "status": "ok"}]
        with _patched_session(conn):
            updated = execution_store.reconcile_plan_steps("r2", trace)

        self.assertEqual(updated, 0)
        status = conn.execute(
            "SELECT status FROM agent.agent_plan_steps WHERE run_id='r2'"
        ).fetchone()["status"]
        self.assertEqual(status, "pending")

    def test_finish_reconciles_a_step_persisted_after_start(self):
        conn = _connection()
        self.addCleanup(conn.close)
        conn.execute(
            "INSERT INTO agent.agent_execution_plans(run_id, execution_status) VALUES ('r3', 'running')"
        )
        with _patched_session(conn):
            # Tool starts before the plan steps exist (plan persisted late).
            step_id = execution_store.start_tool_event("r3", "get_fab_overview", {"start": "2026-01-01"})
            self.assertIsNone(step_id)
            _add_step(conn, "r3", "S01", "get_fab_overview", {"start": "2026-01-01"})
            matched = execution_store.finish_tool_event(
                "r3",
                "get_fab_overview",
                {"start": "2026-01-01"},
                {"status": "ok", "rows": 3, "duration_ms": 12.5},
            )

        self.assertEqual(matched, "S01")
        step = conn.execute(
            "SELECT status, row_count, attempt_count FROM agent.agent_plan_steps WHERE run_id='r3'"
        ).fetchone()
        self.assertEqual(step["status"], "succeeded")
        self.assertEqual(step["row_count"], 3)
        event = conn.execute("SELECT plan_step_id FROM agent.agent_tool_events").fetchone()
        self.assertEqual(event["plan_step_id"], "S01")


if __name__ == "__main__":
    unittest.main()


