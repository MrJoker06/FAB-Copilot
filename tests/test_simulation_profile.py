from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import seed
from app.database import db_session, initialize, validate_department_databases
from app.department_schemas import SCHEMA_VERSION


class SimulationProfileTests(unittest.TestCase):
    def test_end_date_is_strict_and_default_is_fixed(self):
        with patch.dict(os.environ, {"FAB_SIMULATION_END_DATE": "2026-12-25"}, clear=False):
            self.assertEqual(seed._parse_end_date(None), date(2026, 12, 25))
        self.assertEqual(seed._parse_end_date(date(2026, 12, 25)), date(2026, 12, 25))
        for invalid in ("2026-12-25T00:00:00", "2026/12/25", "2026-2-3"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "strict ISO"):
                    seed._parse_end_date(invalid)

    def test_cli_passes_explicit_horizon(self):
        with (
            patch.object(seed, "ensure_department_databases"),
            patch.object(seed, "db_session") as session,
            patch.object(seed, "generate_database", return_value={"ok": True}) as generate,
        ):
            session.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (False,)
            self.assertEqual(seed.main(["--days", "1", "--end-date", "2026-12-25"]), 0)
        generate.assert_called_once_with(days=1, end_date=date(2026, 12, 25))

    def test_small_legacy_generation_has_profile_mix_and_full_e10_days(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.db"
            result = seed.generate_database(path=path, days=4, seed=7, end_date="2026-12-25")
            connection = sqlite3.connect(path)
            try:
                metadata = connection.execute(
                    "SELECT profile_id, classification, start_date, end_date, forecast_start, generated_at, "
                    "source_basis_json, engineering_assumptions_json FROM simulation_metadata"
                ).fetchone()
                mix = connection.execute(
                    "SELECT AVG(technology_nm = 28) FROM lots"
                ).fetchone()[0]
                utilization = connection.execute(
                    "SELECT MIN(productive), MAX(productive) FROM ("
                    "SELECT equipment_id, date(start_time), SUM(CASE WHEN semi_e10_state = 'Productive' "
                    "THEN duration_minutes ELSE 0 END) / 1440.0 AS productive "
                    "FROM equipment_state_intervals GROUP BY equipment_id, date(start_time))"
                ).fetchone()
                coverage = connection.execute(
                    "SELECT MIN(minutes), MAX(minutes) FROM (SELECT equipment_id, date(start_time), "
                    "SUM(duration_minutes) AS minutes FROM equipment_state_intervals "
                    "GROUP BY equipment_id, date(start_time))"
                ).fetchone()
                maxima = {
                    table: connection.execute(f"SELECT MAX(date({column})) FROM {table}").fetchone()[0]
                    for table, column in (
                        ("lots", "start_time"), ("process_runs", "run_time"),
                        ("sensor_readings", "sample_time"), ("equipment_state_intervals", "start_time"),
                        ("equipment_events", "event_time"), ("defect_records", "detected_time"),
                        ("wafer_maps", "detected_time"),
                    )
                }
                migrations = dict(connection.execute(
                    "SELECT version, description FROM schema_migrations WHERE version IN (10, 12, 13)"
                ).fetchall())
            finally:
                connection.close()
            initialize(path)
            connection = sqlite3.connect(path)
            try:
                second_migrations = dict(connection.execute(
                    "SELECT version, description FROM schema_migrations WHERE version IN (10, 12, 13)"
                ).fetchall())
            finally:
                connection.close()
        self.assertEqual(result["horizon"]["end_date"], "2026-12-25")
        self.assertEqual(result["forecast_boundary"], "2026-12-22")
        self.assertEqual(result["profile_id"], seed.MARKET_PROFILE_ID)
        self.assertEqual(metadata[:5], (seed.MARKET_PROFILE_ID, "synthetic_non_production", "2026-12-22", "2026-12-25", "2026-12-22"))
        self.assertIsNotNone(datetime.fromisoformat(metadata[5]).tzinfo)
        self.assertLessEqual(datetime.fromisoformat(metadata[5]), datetime.now(timezone.utc))
        self.assertTrue(all(isinstance(value, str) for value in metadata[6:]))
        self.assertTrue(all(json.loads(value) for value in metadata[6:]))
        self.assertGreater(mix, 0.2)
        self.assertLess(mix, 0.6)
        self.assertGreaterEqual(utilization[0], 0.76)
        self.assertLessEqual(utilization[1], 0.86)
        self.assertEqual(coverage, (1440.0, 1440.0))
        self.assertTrue(all(value <= "2026-12-25" for value in maxima.values()))
        self.assertEqual(migrations, {10: "model catalog capabilities", 12: "model publication compatibility", 13: "legacy schema"})
        self.assertEqual(second_migrations, migrations)

    def test_validator_reports_declared_forecasts_and_horizon_violations(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "FAB_DATABASE_DIR": str(Path(temporary) / "departments"),
            "FAB_MANUFACTURING_DATABASE_PATH": str(Path(temporary) / "departments" / "manufacturing.db"),
            "FAB_EQUIPMENT_DATABASE_PATH": str(Path(temporary) / "departments" / "equipment.db"),
            "FAB_QUALITY_DATABASE_PATH": str(Path(temporary) / "departments" / "quality.db"),
            "FAB_KNOWLEDGE_DATABASE_PATH": str(Path(temporary) / "departments" / "knowledge.db"),
            "FAB_AGENT_DATABASE_PATH": str(Path(temporary) / "departments" / "agent.db"),
        }, clear=False):
            agent_path = Path(temporary) / "departments" / "agent.db"
            agent_path.parent.mkdir(parents=True)
            agent_connection = sqlite3.connect(agent_path)
            try:
                agent_connection.execute(
                    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL)"
                )
                agent_connection.execute(
                    "INSERT INTO schema_migrations VALUES (11, 'model catalog capabilities')"
                )
                agent_connection.commit()
            finally:
                agent_connection.close()
            initialize()
            agent_connection = sqlite3.connect(agent_path)
            try:
                migrations = dict(agent_connection.execute(
                    "SELECT version, description FROM schema_migrations WHERE version IN (10, 12, 13)"
                ).fetchall())
            finally:
                agent_connection.close()
            initialize()
            agent_connection = sqlite3.connect(agent_path)
            try:
                second_migrations = dict(agent_connection.execute(
                    "SELECT version, description FROM schema_migrations WHERE version IN (10, 12, 13)"
                ).fetchall())
            finally:
                agent_connection.close()
            with db_session() as connection:
                connection.execute(
                    "INSERT INTO lots VALUES ('L1', 'P', 28, 'R', 'Normal', '2026-01-01T00:00:00', "
                    "NULL, 'Running', 1, 1, 1.0, 1.0, 0.0)"
                )
                connection.execute(
                    "INSERT INTO process_runs(lot_id, process_step, equipment_id, chamber, recipe, run_time, "
                    "temperature_c, pressure_torr, duration_sec, defect_density, pass_flag) VALUES "
                    "('L1', 'ETCH', 'ETCH-01', 'A', 'r', '2026-12-26T00:00:00', 1, 1, 1, 0, 1)"
                )
                connection.commit()
            missing_checks = validate_department_databases()
            with db_session() as connection:
                connection.execute(
                    "INSERT INTO simulation_metadata VALUES (1, 'test', 'synthetic_non_production', "
                    "'2026-01-01', '2026-12-25', '2026-08-11', '2026-08-10T00:00:00+00:00', 1, '{}', '{}')"
                )
                connection.execute(
                    "INSERT INTO equipment.equipment_events(equipment_id, event_time, event_type, duration_minutes, severity, reason) "
                    "VALUES ('ETCH-01', '2026-08-11T00:00:00', 'Alarm', 1, 'High', 'forecast')"
                )
                connection.execute(
                    "INSERT INTO equipment.equipment_events(equipment_id, event_time, event_type, duration_minutes, severity, reason) "
                    "VALUES ('ETCH-01', '2026-12-26T00:00:00', 'Alarm', 1, 'High', 'test')"
                )
                connection.commit()
            checks = validate_department_databases()
        self.assertEqual(SCHEMA_VERSION, 13)
        self.assertEqual(migrations, {10: "model catalog capabilities", 12: "model publication compatibility", 13: "department schema: agent"})
        self.assertEqual(second_migrations, migrations)
        self.assertEqual(missing_checks["simulation_metadata_status"], "missing")
        self.assertEqual(missing_checks["forecast_process_runs"], 0)
        self.assertEqual(missing_checks["beyond_horizon_process_runs"], 1)
        self.assertEqual(checks["simulation_metadata_status"], "present")
        self.assertEqual(checks["simulation_end_date"], "2026-12-25")
        self.assertEqual(checks["simulation_forecast_start"], "2026-08-11")
        self.assertEqual(checks["forecast_equipment_events"], 1)
        self.assertEqual(checks["beyond_horizon_process_runs"], 1)
        self.assertEqual(checks["beyond_horizon_equipment_events"], 1)

    def test_early_horizon_clamps_the_forecast_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic.db"
            result = seed.generate_database(path=path, days=1, seed=8, end_date="2026-01-01")
            connection = sqlite3.connect(path)
            try:
                metadata = connection.execute(
                    "SELECT start_date, forecast_start, end_date FROM simulation_metadata"
                ).fetchone()
            finally:
                connection.close()
        self.assertEqual(result["forecast_boundary"], "2026-01-01")
        self.assertEqual(metadata, ("2026-01-01", "2026-01-01", "2026-01-01"))
        self.assertEqual(result["simulation_scenarios"], 0)

    def test_scenarios_end_at_the_observed_profile_boundary(self):
        end_day = date(2026, 12, 25)
        forecast_start = date(2026, 8, 11)
        anchor = seed._scenario_anchor_day(end_day, forecast_start)
        self.assertEqual(anchor, date(2026, 8, 10))
        target_day = date(2026, 7, 18)
        windows = [
            seed._scenario_window(date(2024, 12, 26), anchor, active_days)
            for _, _, active_days, _, _, _ in seed.SCENARIO_DEFINITIONS.values()
        ]
        self.assertTrue(all(window is not None for window in windows))
        self.assertTrue(all(window_end == date(2026, 8, 10) for _, window_end in windows))
        self.assertTrue(all(window_start <= target_day <= window_end for window_start, window_end in windows))
        self.assertIsNone(seed._scenario_window(date(2026, 1, 1), date(2025, 12, 31), 45))


if __name__ == "__main__":
    unittest.main()
