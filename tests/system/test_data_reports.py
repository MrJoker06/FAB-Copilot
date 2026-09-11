from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from tests.system.support import isolated_system_environment

isolated_system_environment()

from app.database import db_session, department_paths, initialize, sqlite_journal_mode
from app.manufacturing.processes import MANUFACTURING_STEPS
from app.manufacturing.reports import defect_pareto, equipment_health, equipment_productivity, process_capability, process_pass_rate, recent_excursions, report_bundle, timestamp_bounds
from app.manufacturing.seed import MARKET_PROFILE, MARKET_PROFILE_ID, seed_reference_data

class DataReportsSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_reference_data()
        # Reference snapshots predate DATA-016; make their disposable copy declare the
        # same bounded synthetic profile without touching repository data files.
        with db_session() as connection:
            start_date = connection.execute("SELECT MIN(date(start_time)) FROM lots").fetchone()[0]
            connection.execute("DELETE FROM simulation_metadata")
            connection.execute(
                """INSERT INTO simulation_metadata(
                       singleton_id, profile_id, classification, start_date, end_date, forecast_start,
                       generated_at, seed, source_basis_json, engineering_assumptions_json
                   ) VALUES (1, ?, 'synthetic_non_production', ?, '2026-12-25',
                             '2026-08-11', '2026-08-10T00:00:00+00:00', 20260712, ?, ?)""",
                (
                    MARKET_PROFILE_ID,
                    start_date,
                    json.dumps(MARKET_PROFILE["source_basis"], sort_keys=True),
                    json.dumps(MARKET_PROFILE["engineering_assumptions"], sort_keys=True),
                ),
            )
            connection.commit()

    def test_dashboard_has_manufacturing_data(self):
        dashboard = report_bundle()
        self.assertGreater(dashboard["overview"]["lots"], 300)
        self.assertGreater(dashboard["overview"]["yield_pct"], 80)
        self.assertTrue(dashboard["equipment"])
        defect_types = [row["defect_type"] for row in dashboard["defects"]]
        self.assertEqual(len(defect_types), len(set(defect_types)))
        self.assertTrue(all("process_steps" in row for row in dashboard["defects"]))

    def test_operational_reports_keep_every_process_scope_isolated(self):
        start = (date.today() - timedelta(days=90)).isoformat()
        end = (date.today() + timedelta(days=1)).isoformat()

        for process_step in MANUFACTURING_STEPS:
            with self.subTest(process_step=process_step):
                health = equipment_health(start, end, process_step)
                productivity = equipment_productivity(start, end, process_step)
                defects = defect_pareto(start, end, 25, process_step)

                self.assertTrue(health)
                self.assertTrue(productivity)
                self.assertTrue(all(row["equipment_id"].startswith(f"{process_step}-") for row in health))
                self.assertTrue(all(row["equipment_id"].startswith(f"{process_step}-") for row in productivity))
                self.assertTrue(all(row["process_steps"] == process_step for row in defects))

    def test_process_pass_rate_is_process_scoped_for_every_registered_step(self):
        start = (date.today() - timedelta(days=90)).isoformat()
        end = (date.today() + timedelta(days=1)).isoformat()
        for process_step in MANUFACTURING_STEPS:
            with self.subTest(process_step=process_step):
                rows = process_pass_rate(start, end, process_step)
                self.assertEqual(len(rows), 1)
                self.assertTrue(all(row["process_step"] == process_step for row in rows))
                self.assertTrue(all(row["runs"] >= row["passed_runs"] >= 0 for row in rows))
                equipment_rows = process_pass_rate(start, end, process_step, f"{process_step}-01")
                self.assertEqual(len(equipment_rows), 1)
                self.assertEqual(equipment_rows[0]["equipment_id"], f"{process_step}-01")

    def test_equipment_operational_reports_keep_exact_equipment_scope(self):
        start = (date.today() - timedelta(days=90)).isoformat()
        end = (date.today() + timedelta(days=1)).isoformat()
        equipment_id = "ETCH-04"

        health = equipment_health(start, end, "ETCH", equipment_id)
        productivity = equipment_productivity(start, end, "ETCH", equipment_id)
        excursions = recent_excursions(start, end, 100, "ETCH", equipment_id)

        self.assertTrue(health)
        self.assertTrue(productivity)
        self.assertTrue(excursions)
        self.assertTrue(all(row["equipment_id"] == equipment_id for row in health))
        self.assertTrue(all(row["equipment_id"] == equipment_id for row in productivity))
        self.assertTrue(all(row["equipment_id"] == equipment_id for row in excursions))

    def test_seeded_cvd_drift_is_detectable(self):
        capability = process_capability(process_step="CVD")
        cvd_02 = next(row for row in capability if row["equipment_id"] == "CVD-02")
        peers = [row for row in capability if row["equipment_id"] != "CVD-02"]
        self.assertLess(cvd_02["cpk"], min(row["cpk"] for row in peers))

    def test_capability_range_is_sargable_and_keeps_end_date_inclusive(self):
        self.assertEqual(timestamp_bounds("2026-07-01", "2026-07-13"), ("2026-07-01", "2026-07-14"))
        with db_session() as connection:
            plan = connection.execute(
                "EXPLAIN QUERY PLAN SELECT equipment_id FROM process_runs "
                "WHERE process_step = ? AND run_time >= ? AND run_time < ?",
                ("CMP", "2026-07-01", "2026-07-14"),
            ).fetchall()
        self.assertTrue(any("idx_runs_step_time" in row[3] for row in plan), plan)

    def test_all_manufacturing_steps_have_equipment_and_capability(self):
        with db_session() as connection:
            rows = connection.execute(
                "SELECT process_step, COUNT(DISTINCT equipment_id) AS equipment_count "
                "FROM process_runs GROUP BY process_step"
            ).fetchall()
        equipment_counts = {row["process_step"]: row["equipment_count"] for row in rows}
        self.assertEqual(set(equipment_counts), set(MANUFACTURING_STEPS))
        self.assertTrue(all(count >= 3 for count in equipment_counts.values()))
        for step in MANUFACTURING_STEPS:
            with self.subTest(step=step):
                capability = process_capability(process_step=step)
                self.assertEqual(len(capability), equipment_counts[step])
                self.assertTrue(all(row["metric_name"] and row["metric_unit"] for row in capability))

    def test_expanded_fab_history_has_route_sensor_and_hidden_ground_truth(self):
        with db_session() as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("lots", "process_runs", "sensor_readings", "equipment_state_intervals", "wafer_maps")
            }
            scenarios = connection.execute(
                "SELECT COUNT(*), SUM(visible_to_agent) FROM simulation_scenarios"
            ).fetchone()
            max_operation = connection.execute("SELECT MAX(operation_seq) FROM process_runs").fetchone()[0]
            signal_coverage = connection.execute(
                "SELECT process_step, COUNT(DISTINCT signal_name) FROM sensor_readings GROUP BY process_step"
            ).fetchall()
        self.assertGreaterEqual(counts["lots"], 9000)
        self.assertGreaterEqual(counts["process_runs"], 150000)
        self.assertGreaterEqual(counts["sensor_readings"], 1000000)
        self.assertGreater(counts["equipment_state_intervals"], 25000)
        self.assertEqual(counts["wafer_maps"], counts["lots"])
        self.assertEqual(tuple(scenarios), (9, 0))
        self.assertEqual(max_operation, 18)
        self.assertEqual({row[0] for row in signal_coverage}, set(MANUFACTURING_STEPS))
        self.assertTrue(all(row[1] >= 6 for row in signal_coverage))

    def test_history_declares_its_synthetic_forecast_horizon(self):
        with db_session() as connection:
            max_run = connection.execute("SELECT MAX(date(run_time)) FROM process_runs").fetchone()[0]
            max_defect = connection.execute("SELECT MAX(date(detected_time)) FROM defect_records").fetchone()[0]
            max_wafer_map = connection.execute("SELECT MAX(date(detected_time)) FROM wafer_maps").fetchone()[0]
            metadata = connection.execute(
                "SELECT classification, end_date FROM simulation_metadata WHERE singleton_id = 1"
            ).fetchone()
        self.assertEqual(tuple(metadata), ("synthetic_non_production", "2026-12-25"))
        self.assertLessEqual(max_run, metadata["end_date"])
        self.assertLessEqual(max_defect, metadata["end_date"])
        self.assertLessEqual(max_wafer_map, metadata["end_date"])

    def test_department_databases_are_physically_separated(self):
        paths = department_paths()
        self.assertEqual(set(paths), {"main", "equipment", "quality", "knowledge", "agent"})
        self.assertEqual(len(set(paths.values())), 5)
        self.assertTrue(all(path.exists() for path in paths.values()))
        with db_session() as connection:
            attached = {row[1] for row in connection.execute("PRAGMA database_list")}
            plan_columns = {row[1] for row in connection.execute("PRAGMA agent.table_info(agent_execution_plans)")}
            step_columns = {row[1] for row in connection.execute("PRAGMA agent.table_info(agent_plan_steps)")}
            tool_columns = {row[1] for row in connection.execute("PRAGMA agent.table_info(agent_tool_events)")}
        self.assertTrue({"main", "equipment", "quality", "knowledge", "agent"}.issubset(attached))
        self.assertTrue({"plan_id", "definition_status", "execution_status"}.issubset(plan_columns))
        self.assertTrue({"step_id", "status", "attempt_count"}.issubset(step_columns))
        self.assertTrue({"plan_step_id", "started_at", "completed_at"}.issubset(tool_columns))

    def test_sqlite_journal_mode_is_safe_for_wsl_mounted_databases(self):
        with patch.dict(os.environ, {"FAB_SQLITE_JOURNAL_MODE": "auto"}):
            self.assertEqual(sqlite_journal_mode(Path("/mnt/d/fab.db")), "DELETE")
            self.assertEqual(sqlite_journal_mode(Path("/tmp/fab.db")), "WAL")
        with patch.dict(os.environ, {"FAB_SQLITE_JOURNAL_MODE": "TRUNCATE"}):
            self.assertEqual(sqlite_journal_mode(Path("/mnt/d/fab.db")), "TRUNCATE")

    def test_agent_run_migration_backfills_question_and_user_message(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy-agent.db"
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """CREATE TABLE chat_sessions (
                       session_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'demo-fab',
                       owner_user_id TEXT NOT NULL DEFAULT 'local-user', title TEXT NOT NULL,
                       created_at TEXT NOT NULL, updated_at TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
                       archived_at TEXT, last_message_preview TEXT NOT NULL DEFAULT ''
                   );
                   CREATE TABLE chat_messages (
                       message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                       session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                       role TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
                       client_message_id TEXT, created_at TEXT NOT NULL
                   );
                   CREATE TABLE agent_runs (
                       run_id TEXT PRIMARY KEY,
                       session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                       assistant_message_id INTEGER REFERENCES chat_messages(message_id) ON DELETE SET NULL,
                       model TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
                       started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
                       first_token_ms REAL, duration_ms REAL,
                       input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
                       error_message TEXT
                   );
                   INSERT INTO chat_sessions(session_id, title, created_at, updated_at)
                   VALUES ('legacy-session', '用户修改后的名称', '2026-07-17', '2026-07-17');
                   INSERT INTO chat_messages(session_id, role, content, created_at)
                   VALUES ('legacy-session', 'user', '分析 ETCH-04 最近三天故障', '2026-07-17T01:00:00Z');
                   INSERT INTO chat_messages(session_id, role, content, created_at)
                   VALUES ('legacy-session', 'assistant', '分析结果', '2026-07-17T01:01:00Z');
                   INSERT INTO agent_runs(
                       run_id, session_id, assistant_message_id, model, mode, status, started_at, completed_at
                   ) VALUES ('legacy-run', 'legacy-session', 2, 'test-model', 'test', 'success',
                             '2026-07-17T01:00:00Z', '2026-07-17T01:01:00Z');"""
            )
            connection.commit()
            connection.close()

            initialize(database_path)
            connection = sqlite3.connect(database_path)
            row = connection.execute(
                "SELECT user_message_id, question_preview FROM agent_runs WHERE run_id = 'legacy-run'"
            ).fetchone()
            columns = {item[1] for item in connection.execute("PRAGMA table_info(agent_runs)")}
            connection.close()

        self.assertEqual(row, (1, "分析 ETCH-04 最近三天故障"))
        self.assertTrue({"user_message_id", "question_preview"}.issubset(columns))

    def test_recent_excursions_supports_process_filter(self):
        rows = recent_excursions(process_step="CMP", limit=20)
        self.assertTrue(rows)
        self.assertTrue(all(row["process_step"] == "CMP" for row in rows))

if __name__ == "__main__":
    unittest.main()
