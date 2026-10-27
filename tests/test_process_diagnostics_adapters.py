from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.agent_runtime.tools.contracts import ToolSourceKind
from app.integrations.manufacturing.fake_process_diagnostics import (
    FakeProcessDiagnosticsAdapter,
)
from app.integrations.manufacturing.sqlite_process_diagnostics import (
    SQLiteProcessDiagnosticsAdapter,
)
from app.manufacturing import reports
from app.manufacturing.process_diagnostics.contracts import (
    DiagnosticsDataError,
    DiagnosticsQuery,
    DiagnosticsTimeoutError,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "analyst"
    roles: tuple[str, ...] = ("analyst",)


class ProcessDiagnosticsAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.manufacturing = root / "manufacturing.db"
        self.equipment = root / "equipment.db"
        self._make_manufacturing()
        self._make_equipment()
        self.principal = Principal()
        self.capability = DiagnosticsQuery(
            "capability", date(2026, 10, 1), date(2026, 10, 24), "CMP"
        )
        self.sensors = DiagnosticsQuery(
            "sensors", date(2026, 10, 1), date(2026, 10, 24), "CMP"
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _make_manufacturing(self) -> None:
        with sqlite3.connect(self.manufacturing) as connection:
            connection.execute(
                """CREATE TABLE process_runs (
                equipment_id TEXT, run_time TEXT, measurement_value REAL,
                measurement_name TEXT, measurement_unit TEXT, spec_lsl REAL,
                spec_usl REAL, process_step TEXT)"""
            )
            connection.executemany(
                "INSERT INTO process_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("CMP-01", "2026-10-02", 1.0, "thickness", "nm", 0.5, 1.5, "CMP"),
                    ("CMP-01", "2026-10-03", 1.2, "thickness", "nm", 0.5, 1.5, "CMP"),
                    ("CMP-02", "2026-10-03", 1.0, "thickness", "nm", 0.5, 1.5, "CMP"),
                    ("CMP-02", "2026-10-04", 1.0, "thickness", "nm", 0.5, 1.5, "CMP"),
                    ("CMP-03", "2026-10-04", 1.0, "thickness", "nm", None, 1.5, "CMP"),
                    ("CMP-03", "2026-10-05", 1.2, "thickness", "nm", None, 1.5, "CMP"),
                    ("CMP-04", "2026-10-04", 1.0, "thickness", "nm", None, None, "CMP"),
                    ("CMP-04", "2026-10-05", 1.2, "thickness", "nm", None, None, "CMP"),
                    ("CMP-05", "2026-10-05", None, "thickness", "nm", 0.5, 1.5, "CMP"),
                    ("ETCH-01", "2026-10-05", 9.0, "depth", "nm", 8.0, 10.0, "ETCH"),
                ],
            )

    def _make_equipment(self) -> None:
        with sqlite3.connect(self.equipment) as connection:
            connection.execute(
                """CREATE TABLE sensor_readings (
                sample_time TEXT, process_step TEXT, equipment_id TEXT,
                signal_name TEXT, signal_unit TEXT, is_missing INTEGER,
                is_outlier INTEGER, signal_value REAL)"""
            )
            connection.executemany(
                "INSERT INTO sensor_readings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("2026-10-02", "CMP", "CMP-01", "pressure", "kPa", 0, 0, 1.0),
                    ("2026-10-03", "CMP", "CMP-01", "pressure", "kPa", 1, 1, None),
                    ("2026-10-03", "CMP", "CMP-01", "temperature", "C", 0, 0, 22.0),
                    ("2026-10-04", "CMP", "CMP-02", "pressure", "kPa", 1, 0, None),
                    ("2026-10-05", "ETCH", "CMP-01", "pressure", "kPa", 0, 1, 2.0),
                ],
            )

    @staticmethod
    @contextmanager
    def _old_session(path: Path):
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def test_capability_exactly_matches_legacy_sql_for_null_and_spec_variants(self):
        adapter = SQLiteProcessDiagnosticsAdapter(
            self.manufacturing, self.equipment, demo_tenant_id="demo"
        )
        with patch.object(
            reports, "db_session", lambda: self._old_session(self.manufacturing)
        ):
            expected = reports.process_capability("2026-10-01", "2026-10-24", "CMP")
        actual = list(adapter.fetch(self.capability, self.principal).rows)
        self.assertEqual(actual, expected)
        self.assertEqual(
            [row["equipment_id"] for row in actual],
            ["CMP-02", "CMP-04", "CMP-01", "CMP-03"],
        )
        self.assertIsNone(actual[0]["cpk"])
        self.assertIsNone(actual[1]["spec_lsl"])
        self.assertIsNone(actual[1]["spec_usl"])

    def test_sensor_exactly_matches_legacy_sql_and_combined_filter(self):
        adapter = SQLiteProcessDiagnosticsAdapter(
            self.manufacturing, self.equipment, demo_tenant_id="demo"
        )
        with patch.object(
            reports, "db_session", lambda: self._old_session(self.equipment)
        ):
            expected = reports.sensor_summary("2026-10-01", "2026-10-24", "CMP")
        actual = list(adapter.fetch(self.sensors, self.principal).rows)
        self.assertEqual(actual, expected)
        filtered = DiagnosticsQuery(
            "sensors",
            date(2026, 10, 1),
            date(2026, 10, 24),
            "CMP",
            "CMP-01",
            "pressure",
        )
        self.assertEqual(
            list(adapter.fetch(filtered, self.principal).rows),
            [
                {
                    "process_step": "CMP",
                    "equipment_id": "CMP-01",
                    "signal_name": "pressure",
                    "signal_unit": "kPa",
                    "samples": 2,
                    "missing_samples": 1,
                    "flagged_outliers": 1,
                    "mean_value": 1.0,
                    "min_value": 1.0,
                    "max_value": 1.0,
                }
            ],
        )
        all_missing = DiagnosticsQuery(
            "sensors",
            date(2026, 10, 1),
            date(2026, 10, 24),
            "CMP",
            "CMP-02",
            "pressure",
        )
        row = adapter.fetch(all_missing, self.principal).rows[0]
        self.assertEqual(
            (row["mean_value"], row["min_value"], row["max_value"]), (None, None, None)
        )

    def test_sql_values_are_parameterized_and_unrelated_source_is_not_required(self):
        missing = Path(self.directory.name) / "missing.db"
        adapter = SQLiteProcessDiagnosticsAdapter(
            self.manufacturing, missing, demo_tenant_id="demo"
        )
        self.assertTrue(adapter.fetch(self.capability, self.principal).rows)
        injected = DiagnosticsQuery(
            "sensors", date(2026, 10, 1), date(2026, 10, 24), "CMP", "CMP-01' OR 1=1 --"
        )
        sensors_only = SQLiteProcessDiagnosticsAdapter(
            missing, self.equipment, demo_tenant_id="demo"
        )
        self.assertEqual(sensors_only.fetch(injected, self.principal).rows, ())
        self.assertFalse(missing.exists())

    def test_tenant_and_missing_source_fail_without_connecting_or_creating(self):
        missing = Path(self.directory.name) / "not-present.db"
        adapter = SQLiteProcessDiagnosticsAdapter(
            missing, self.equipment, demo_tenant_id="demo"
        )
        with patch(
            "app.integrations.manufacturing.sqlite_process_diagnostics.sqlite3.connect"
        ) as connect:
            with self.assertRaisesRegex(DiagnosticsDataError, "unavailable") as error:
                adapter.fetch(self.capability, Principal("other"))
            connect.assert_not_called()
        self.assertNotIn(str(missing), str(error.exception))
        with self.assertRaisesRegex(DiagnosticsDataError, "unavailable"):
            adapter.fetch(self.capability, self.principal)
        self.assertFalse(missing.exists())
        available = SQLiteProcessDiagnosticsAdapter(
            self.manufacturing, self.equipment, demo_tenant_id="demo"
        )
        with (
            patch.object(Path, "is_file", side_effect=PermissionError("/private")),
            self.assertRaisesRegex(DiagnosticsDataError, "unavailable") as error,
        ):
            available.fetch(self.capability, self.principal)
        self.assertNotIn("private", str(error.exception))

    def test_readonly_query_only_no_attach_and_close_failures_are_sanitized(self):
        adapter = SQLiteProcessDiagnosticsAdapter(
            self.manufacturing, self.equipment, demo_tenant_id="demo"
        )
        original_connect = sqlite3.connect
        calls: list[object] = []

        class ConnectionSpy:
            def __init__(self, connection, *, close_error=False):
                self.connection = connection
                self.close_error = close_error
                self.executed: list[str] = []
                self.closed = False

            def __setattr__(self, name, value):
                if name == "row_factory":
                    self.connection.row_factory = value
                    return
                object.__setattr__(self, name, value)

            def execute(self, sql, *args):
                self.executed.append(sql)
                return self.connection.execute(sql, *args)

            def set_progress_handler(self, *args):
                return self.connection.set_progress_handler(*args)

            def close(self):
                self.connection.close()
                self.closed = True
                if self.close_error:
                    raise sqlite3.OperationalError("/private/source.db")

        def connect(*args, **kwargs):
            spy = ConnectionSpy(original_connect(*args, **kwargs))
            calls.append((args, kwargs, spy))
            return spy

        with patch(
            "app.integrations.manufacturing.sqlite_process_diagnostics.sqlite3.connect",
            side_effect=connect,
        ):
            adapter.fetch(self.capability, self.principal)
        args, kwargs, spy = calls[0]
        self.assertIn("mode=ro", args[0])
        self.assertTrue(kwargs["uri"])
        self.assertIn("PRAGMA query_only = ON", spy.executed)
        self.assertFalse(any("ATTACH" in sql.upper() for sql in spy.executed))
        self.assertTrue(spy.closed)

        def bad_close(*args, **kwargs):
            return ConnectionSpy(original_connect(*args, **kwargs), close_error=True)

        with (
            patch(
                "app.integrations.manufacturing.sqlite_process_diagnostics.sqlite3.connect",
                side_effect=bad_close,
            ),
            self.assertRaisesRegex(DiagnosticsDataError, "unavailable") as error,
        ):
            adapter.fetch(self.capability, self.principal)
        self.assertNotIn("private", str(error.exception))

    def test_progress_timeout_and_fake_fixture_copy_are_isolated(self):
        adapter = SQLiteProcessDiagnosticsAdapter(
            self.manufacturing,
            self.equipment,
            demo_tenant_id="demo",
            query_timeout_ms=1,
        )
        original_connect = sqlite3.connect

        class TimeoutConnection:
            def __init__(self, connection):
                self.connection = connection
                self.timed_out = False

            def __setattr__(self, name, value):
                if name == "row_factory":
                    self.connection.row_factory = value
                    return
                object.__setattr__(self, name, value)

            def execute(self, *args):
                if self.timed_out:
                    raise sqlite3.OperationalError("interrupted")
                return self.connection.execute(*args)

            def set_progress_handler(self, handler, count):
                del count
                self.timed_out = bool(handler())

            def close(self):
                self.connection.close()

        with (
            patch(
                "app.integrations.manufacturing.sqlite_process_diagnostics.time.monotonic",
                side_effect=(0, 0.002),
            ),
            patch(
                "app.integrations.manufacturing.sqlite_process_diagnostics.sqlite3.connect",
                side_effect=lambda *args, **kwargs: TimeoutConnection(
                    original_connect(*args, **kwargs)
                ),
            ),
            self.assertRaisesRegex(DiagnosticsTimeoutError, "timed out") as error,
        ):
            adapter.fetch(self.capability, self.principal)
        self.assertNotIn(str(self.manufacturing), str(error.exception))

        source_rows = ({"process_step": "CMP"},)
        fake = FakeProcessDiagnosticsAdapter("demo", {self.capability: source_rows})
        source_rows[0]["process_step"] = "ETCH"
        first = fake.fetch(self.capability, self.principal)
        first.rows[0]["process_step"] = "MUTATED"
        second = fake.fetch(self.capability, self.principal)
        self.assertEqual(second.rows, ({"process_step": "CMP"},))
        self.assertEqual(fake.calls, [self.capability, self.capability])
        self.assertEqual(second.source.source_kind, ToolSourceKind.FAKE)
        with self.assertRaises(DiagnosticsDataError):
            fake.fetch(self.capability, Principal("other"))


if __name__ == "__main__":
    unittest.main()
