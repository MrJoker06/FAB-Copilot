from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_ci_data


class PrepareCiDataTests(unittest.TestCase):
    @staticmethod
    def valid_report() -> dict:
        return {
            "departments": {
                "manufacturing": {"quick_check": "ok", "tables": {"lots": 9_000}},
                "equipment": {"quick_check": "ok", "tables": {"sensor_readings": 1_000_000}},
                "quality": {"quick_check": "ok", "tables": {}},
                "knowledge": {"quick_check": "ok", "tables": {}},
                "agent": {"quick_check": "ok", "tables": {}},
            },
            "governance": {
                "quick_check": "ok",
                "simulation_metadata_status": "present",
                "simulation_end_date": "2026-12-25",
                "simulation_forecast_start": "2026-08-11",
                "beyond_horizon_lots": 0,
                "beyond_horizon_process_runs": 0,
                "beyond_horizon_sensor_readings": 0,
                "beyond_horizon_equipment_state_intervals": 0,
                "beyond_horizon_equipment_events": 0,
                "beyond_horizon_defect_records": 0,
                "beyond_horizon_wafer_maps": 0,
            },
        }

    def test_refuses_outside_ci_before_touching_databases(self):
        with (
            patch.object(prepare_ci_data, "_ci_enabled", return_value=False),
            patch.object(prepare_ci_data, "reject_existing_reference_databases") as reject,
            self.assertRaisesRegex(RuntimeError, "outside CI=true"),
        ):
            prepare_ci_data.prepare_ci_data()
        reject.assert_not_called()

    def test_refuses_existing_reference_databases(self):
        with tempfile.TemporaryDirectory() as temporary:
            existing = Path(temporary) / "existing-ci-reference.db"
            existing.touch()
            with self.assertRaisesRegex(RuntimeError, "fresh database set"):
                prepare_ci_data.reject_existing_reference_databases((existing,))

    def test_generation_catalog_and_validation_are_ordered(self):
        calls: list[str] = []
        with (
            patch.object(prepare_ci_data, "_ci_enabled", return_value=True),
            patch.object(prepare_ci_data, "reject_database_path_overrides", side_effect=lambda: calls.append("paths")),
            patch.object(prepare_ci_data, "reject_existing_reference_databases", side_effect=lambda: calls.append("reject")),
            patch.object(prepare_ci_data, "seed_main", side_effect=lambda args: calls.append("seed") or 0) as seed,
            patch.object(prepare_ci_data, "ensure_model_catalog", side_effect=lambda: calls.append("catalog")),
            patch.object(prepare_ci_data, "validate_ci_data", side_effect=lambda: calls.append("validate") or {"ok": True}),
        ):
            self.assertEqual(prepare_ci_data.prepare_ci_data(), {"ok": True})
        self.assertEqual(calls, ["paths", "reject", "seed", "catalog", "validate"])
        seed.assert_called_once_with(["--force", "--days", "730", "--end-date", "2026-12-25"])

    def test_generation_failure_stops_before_catalog(self):
        with (
            patch.object(prepare_ci_data, "_ci_enabled", return_value=True),
            patch.object(prepare_ci_data, "reject_database_path_overrides"),
            patch.object(prepare_ci_data, "reject_existing_reference_databases"),
            patch.object(prepare_ci_data, "seed_main", return_value=1),
            patch.object(prepare_ci_data, "ensure_model_catalog") as catalog,
            self.assertRaisesRegex(RuntimeError, "exit code 1"),
        ):
            prepare_ci_data.prepare_ci_data()
        catalog.assert_not_called()

    def test_path_override_stops_before_existing_check_and_seed(self):
        with (
            patch.object(prepare_ci_data, "_ci_enabled", return_value=True),
            patch.object(prepare_ci_data, "reject_database_path_overrides", side_effect=RuntimeError("path override")),
            patch.object(prepare_ci_data, "reject_existing_reference_databases") as existing,
            patch.object(prepare_ci_data, "seed_main") as seed,
            self.assertRaisesRegex(RuntimeError, "path override"),
        ):
            prepare_ci_data.prepare_ci_data()
        existing.assert_not_called()
        seed.assert_not_called()

    def test_path_override_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "FAB_DATABASE_DIR"):
            prepare_ci_data.reject_database_path_overrides({"FAB_DATABASE_DIR": "/tmp/redirect"})

    def test_default_ci_database_paths_are_accepted(self):
        with patch.object(prepare_ci_data, "department_paths", return_value=prepare_ci_data.EXPECTED_DEPARTMENT_PATHS):
            prepare_ci_data.reject_database_path_overrides({})

    def test_validation_requires_governance_and_published_catalog_rows(self):
        with patch.object(prepare_ci_data.manage_databases, "manifest", return_value={"governance": {"quick_check": "broken"}}):
            with self.assertRaisesRegex(RuntimeError, "manifest"):
                prepare_ci_data.validate_ci_data()

    def test_validation_rejects_missing_published_model_rows(self):
        @contextmanager
        def fake_session():
            class Connection:
                def execute(self, *args):
                    class Cursor:
                        @staticmethod
                        def fetchall():
                            return [("deepseekv4-flash",)]
                    return Cursor()
            yield Connection()

        report = self.valid_report()
        with (
            patch.object(prepare_ci_data.manage_databases, "manifest", return_value=report),
            patch.object(prepare_ci_data, "db_session", fake_session),
            self.assertRaisesRegex(RuntimeError, "deepseekv4-pro"),
        ):
            prepare_ci_data.validate_ci_data()

    def test_validation_rejects_wrong_horizon_small_dataset_and_beyond_horizon_rows(self):
        for label, mutate, expected in (
            ("end", lambda report: report["governance"].update(simulation_end_date="2026-12-24"), "end date"),
            ("forecast", lambda report: report["governance"].update(simulation_forecast_start="2026-08-12"), "forecast start"),
            ("beyond", lambda report: report["governance"].update(beyond_horizon_lots=1), "beyond its horizon"),
            ("lots", lambda report: report["departments"]["manufacturing"]["tables"].update(lots=8_999), "too few lots"),
            ("sensors", lambda report: report["departments"]["equipment"]["tables"].update(sensor_readings=999_999), "too few sensor readings"),
            ("department", lambda report: report["departments"].pop("quality"), "manifest validation"),
            ("horizon-key", lambda report: report["governance"].pop("beyond_horizon_lots"), "missing horizon checks"),
        ):
            with self.subTest(label=label):
                report = self.valid_report()
                mutate(report)
                with patch.object(prepare_ci_data.manage_databases, "manifest", return_value=report):
                    with self.assertRaisesRegex(RuntimeError, expected):
                        prepare_ci_data.validate_ci_data()
