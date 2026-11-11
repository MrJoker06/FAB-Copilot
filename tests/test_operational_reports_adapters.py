from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.agent_runtime.tools.contracts import ToolSourceKind
from app.core.sqlite_support import install_sqlite_functions
from app.demo_data.tool_sources.operational_reports import (
    FakeOperationalReportsAdapter,
)
from app.tools.operational_reports.data_source import (
    SQLiteOperationalReportsAdapter,
)
import app.persistence.database as _report_app_persistence_database
import app.tools.operational_reports.reports as _report_app_tools_operational_reports_reports

from app.tools.operational_reports.contracts import (
    OperationalReportDataError,
    OperationalReportQuery,
    OperationalReportTimeoutError,
)


class Principal:
    tenant_id = "demo"
    user_id = "analyst"
    roles = ("analyst",)


class _ConnectionSpy:
    def __init__(self, connection: sqlite3.Connection) -> None:
        object.__setattr__(self, "connection", connection)
        object.__setattr__(self, "executed", [])
        object.__setattr__(self, "closed", False)

    def __setattr__(self, name: str, value: object) -> None:
        if name == "row_factory":
            self.connection.row_factory = value
            return
        object.__setattr__(self, name, value)

    def execute(self, sql: str, parameters: object = ()):
        self.executed.append(sql)
        return self.connection.execute(sql, parameters)

    def set_progress_handler(self, handler: object, steps: int) -> None:
        self.connection.set_progress_handler(handler, steps)

    def create_function(self, *args: object, **kwargs: object) -> None:
        self.connection.create_function(*args, **kwargs)

    def close(self) -> None:
        self.closed = True
        self.connection.close()


class _CloseFailConnection(_ConnectionSpy):
    def close(self) -> None:
        self.connection.close()
        raise sqlite3.OperationalError("private close detail")


class _ExecuteFailConnection(_ConnectionSpy):
    def execute(self, sql: str, parameters: object = ()):
        if sql.lstrip().upper().startswith("SELECT"):
            raise sqlite3.OperationalError("private execution marker")
        return super().execute(sql, parameters)


class _TimeoutConnection:
    row_factory = None

    def __init__(self) -> None:
        self.handler = None
        self.closed = False

    def execute(self, _sql: str, _parameters: object = ()) -> _TimeoutConnection:
        if self.handler is not None:
            self.handler()
            raise sqlite3.OperationalError("interrupted")
        return self

    def set_progress_handler(self, handler: object, _steps: int) -> None:
        self.handler = handler

    def create_function(self, *_args: object, **_kwargs: object) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _TimeoutCloseFailConnection(_TimeoutConnection):
    def close(self) -> None:
        super().close()
        raise sqlite3.OperationalError("private close detail")


class OperationalReportsAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.equipment = root / "equipment.db"
        self.quality = root / "quality.db"
        self.manufacturing = root / "manufacturing.db"
        self._make_equipment()
        self._make_quality()
        self._make_manufacturing()
        self.principal = Principal()
        self.adapter = SQLiteOperationalReportsAdapter(
            equipment_path=self.equipment,
            quality_path=self.quality,
            manufacturing_path=self.manufacturing,
            demo_tenant_id="demo",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _make_equipment(self) -> None:
        with sqlite3.connect(self.equipment) as connection:
            connection.execute(
                """CREATE TABLE equipment_state_intervals (
                equipment_id TEXT, start_time TEXT, duration_minutes REAL,
                semi_e10_state TEXT)"""
            )
            connection.executemany(
                "INSERT INTO equipment_state_intervals VALUES (?, ?, ?, ?)",
                [
                    ("CMP-01", "2026-01-01T00:00", 0.04, "Productive"),
                    ("CMP-01", "2026-01-01T01:00", 0.01, "Unscheduled Downtime"),
                    ("CMP-02", "2026-01-02", 10.0, "Productive"),
                    ("CMP-02", "2026-01-02", 5.0, "Scheduled Downtime"),
                    ("CMP-04", "2026-01-01", 0.04, "Productive"),
                    ("ETCH-01", "2026-01-02", 9.0, "Productive"),
                    ("CMP-03", "2026-01-04", 99.0, "Productive"),
                ],
            )

    def _make_quality(self) -> None:
        with sqlite3.connect(self.quality) as connection:
            connection.execute(
                """CREATE TABLE defect_records (
                lot_id TEXT, detected_time TEXT, process_step TEXT,
                defect_type TEXT, count INTEGER)"""
            )
            connection.executemany(
                "INSERT INTO defect_records VALUES (?, ?, ?, ?, ?)",
                [
                    ("L1", "2026-01-01", "CMP", "Scratch", 10),
                    ("L2", "2026-01-01", "CMP", "Scratch", 5),
                    ("L2", "2026-01-02", "ETCH", "Particle", 15),
                    ("L3", "2026-01-02", "ETCH", "Particle", 5),
                    ("L4", "2026-01-03", "CMP", "Void", 10),
                    ("L5", "2026-01-04", "CMP", "Zero", 0),
                ],
            )

    def _make_manufacturing(self) -> None:
        with sqlite3.connect(self.manufacturing) as connection:
            connection.execute(
                """CREATE TABLE process_runs (
                run_time TEXT, lot_id TEXT, process_step TEXT, equipment_id TEXT,
                excursion_code TEXT, thickness_nm REAL, uniformity_pct REAL,
                defect_density REAL, measurement_name TEXT, measurement_value REAL,
                measurement_unit TEXT, spec_lsl REAL, spec_usl REAL)"""
            )
            connection.executemany(
                "INSERT INTO process_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "2026-01-01T23:59",
                        "L1",
                        "CMP",
                        "CMP-01",
                        "E1",
                        1.0,
                        None,
                        0.1,
                        "thickness",
                        None,
                        "nm",
                        None,
                        2.0,
                    ),
                    (
                        "2026-01-02",
                        "L2",
                        "CMP",
                        "CMP-01",
                        "",
                        None,
                        0.3,
                        0.2,
                        "thickness",
                        1.2,
                        "nm",
                        0.5,
                        2.0,
                    ),
                    (
                        "2026-01-03",
                        "L3",
                        "CMP",
                        "CMP-02",
                        "E3",
                        1.1,
                        0.2,
                        0.4,
                        "thickness",
                        1.1,
                        "nm",
                        0.5,
                        2.0,
                    ),
                    (
                        "2026-01-03",
                        "L4",
                        "ETCH",
                        "CMP-01",
                        "E4",
                        3.0,
                        0.1,
                        0.3,
                        "depth",
                        3.0,
                        "nm",
                        2.0,
                        4.0,
                    ),
                    (
                        "2026-01-04",
                        "L5",
                        "CMP",
                        "CMP-01",
                        None,
                        1.0,
                        0.1,
                        0.3,
                        "thickness",
                        1.0,
                        "nm",
                        0.5,
                        2.0,
                    ),
                ],
            )

    @staticmethod
    @contextmanager
    def _legacy_session(path: Path):
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        install_sqlite_functions(connection)
        try:
            yield connection
        finally:
            connection.close()

    def _legacy(self, path: Path, callback):
        with patch.object(_report_app_persistence_database, "db_session", lambda: self._legacy_session(path)):
            return callback()

    def test_all_three_exactly_match_legacy_fixed_queries(self) -> None:
        cases = (
            (
                OperationalReportQuery(
                    "productivity", date(2026, 1, 1), date(2026, 1, 3), "CMP"
                ),
                self.equipment,
                lambda: _report_app_tools_operational_reports_reports.equipment_productivity(
                    "2026-01-01", "2026-01-03", "CMP"
                ),
            ),
            (
                OperationalReportQuery(
                    "defects", date(2026, 1, 1), date(2026, 1, 3), limit=1
                ),
                self.quality,
                lambda: _report_app_tools_operational_reports_reports.defect_pareto("2026-01-01", "2026-01-03", 1),
            ),
            (
                OperationalReportQuery(
                    "excursions",
                    date(2026, 1, 1),
                    date(2026, 1, 3),
                    "CMP",
                    "CMP-01",
                    20,
                ),
                self.manufacturing,
                lambda: _report_app_tools_operational_reports_reports.recent_excursions(
                    "2026-01-01", "2026-01-03", 20, "CMP", "CMP-01"
                ),
            ),
        )
        for query, source, legacy in cases:
            with self.subTest(query=query):
                self.assertEqual(
                    self.adapter.fetch(query, self.principal).rows,
                    tuple(self._legacy(source, legacy)),
                )

    def test_productivity_preserves_prefix_scope_rounding_and_equipment_priority(
        self,
    ) -> None:
        process = OperationalReportQuery(
            "productivity", date(2026, 1, 1), date(2026, 1, 3), "CMP"
        )
        rows = self.adapter.fetch(process, self.principal).rows
        self.assertEqual(
            [row["equipment_id"] for row in rows], ["CMP-02", "CMP-01", "CMP-04"]
        )
        tiny = next(row for row in rows if row["equipment_id"] == "CMP-01")
        self.assertEqual(
            (
                tiny["recorded_minutes"],
                tiny["productive_minutes"],
                tiny["productive_pct"],
            ),
            (0.1, 0.0, 80.0),
        )
        rounded = next(row for row in rows if row["equipment_id"] == "CMP-04")
        self.assertEqual(
            (
                rounded["recorded_minutes"],
                rounded["productive_minutes"],
                rounded["productive_pct"],
            ),
            (0.0, 0.0, 100.0),
        )
        exact = OperationalReportQuery(
            "productivity", date(2026, 1, 1), date(2026, 1, 3), equipment_id="CMP-01"
        )
        self.assertEqual(len(self.adapter.fetch(exact, self.principal).rows), 1)
        self.assertFalse((Path(self.directory.name) / "unrelated.db").exists())

    def test_defects_preserve_window_denominator_limit_and_exact_process_filter(
        self,
    ) -> None:
        top = self.adapter.fetch(
            OperationalReportQuery(
                "defects", date(2026, 1, 1), date(2026, 1, 3), limit=1
            ),
            self.principal,
        ).rows
        self.assertEqual(top[0]["defect_type"], "Particle")
        self.assertEqual(top[0]["share_pct"], 44.44)
        self.assertLess(top[0]["share_pct"], 100.0)
        filtered = self.adapter.fetch(
            OperationalReportQuery(
                "defects", date(2026, 1, 1), date(2026, 1, 3), "CMP", limit=25
            ),
            self.principal,
        ).rows
        self.assertEqual({row["defect_type"] for row in filtered}, {"Scratch", "Void"})
        self.assertTrue(all(row["process_steps"] == "CMP" for row in filtered))
        zero = self.adapter.fetch(
            OperationalReportQuery(
                "defects", date(2026, 1, 4), date(2026, 1, 4), limit=25
            ),
            self.principal,
        ).rows
        self.assertEqual(zero[0]["share_pct"], None)
        empty = self.adapter.fetch(
            OperationalReportQuery(
                "defects", date(2026, 2, 1), date(2026, 2, 1), limit=25
            ),
            self.principal,
        ).rows
        self.assertEqual(empty, ())

    def test_excursions_apply_joint_filters_final_day_order_limit_and_bound_literals(
        self,
    ) -> None:
        joint = self.adapter.fetch(
            OperationalReportQuery(
                "excursions", date(2026, 1, 1), date(2026, 1, 3), "CMP", "CMP-01", 20
            ),
            self.principal,
        ).rows
        self.assertEqual([row["lot_id"] for row in joint], ["L2", "L1"])
        self.assertEqual(joint[0]["excursion_code"], "")
        self.assertIsNone(joint[0]["thickness_nm"])
        self.assertEqual(
            self.adapter.fetch(
                OperationalReportQuery(
                    "excursions", date(2026, 1, 1), date(2026, 1, 3), "CMP", "CMP-01", 1
                ),
                self.principal,
            ).rows,
            (joint[0],),
        )
        injected = OperationalReportQuery(
            "excursions",
            date(2026, 1, 1),
            date(2026, 1, 3),
            "CMP",
            "CMP-01' OR 1=1 --",
            20,
        )
        self.assertEqual(self.adapter.fetch(injected, self.principal).rows, ())

    def test_related_source_only_tenant_missing_and_permission_fail_safely(
        self,
    ) -> None:
        missing = Path(self.directory.name) / "missing.db"
        equipment_only = SQLiteOperationalReportsAdapter(
            equipment_path=self.equipment,
            quality_path=missing,
            manufacturing_path=missing,
            demo_tenant_id="demo",
        )
        query = OperationalReportQuery(
            "productivity", date(2026, 1, 1), date(2026, 1, 3)
        )
        self.assertTrue(equipment_only.fetch(query, self.principal).rows)
        self.assertFalse(missing.exists())
        with patch(
            "app.tools.operational_reports.data_source.sqlite3.connect"
        ) as connect:
            with self.assertRaisesRegex(OperationalReportDataError, "unavailable"):
                self.adapter.fetch(
                    query,
                    type(
                        "Other", (), {"tenant_id": "other", "user_id": "u", "roles": ()}
                    )(),
                )
            connect.assert_not_called()
        with (
            patch.object(Path, "is_file", side_effect=PermissionError("/private/path")),
            self.assertRaisesRegex(OperationalReportDataError, "unavailable") as error,
        ):
            self.adapter.fetch(query, self.principal)
        self.assertNotIn("private", str(error.exception))

    def test_selected_missing_sources_fail_without_connecting_or_creating(self) -> None:
        missing = Path(self.directory.name) / "selected-missing.db"
        cases = (
            (
                SQLiteOperationalReportsAdapter(
                    equipment_path=missing, demo_tenant_id="demo"
                ),
                OperationalReportQuery(
                    "productivity", date(2026, 1, 1), date(2026, 1, 3)
                ),
            ),
            (
                SQLiteOperationalReportsAdapter(
                    quality_path=missing, demo_tenant_id="demo"
                ),
                OperationalReportQuery(
                    "defects", date(2026, 1, 1), date(2026, 1, 3), limit=1
                ),
            ),
            (
                SQLiteOperationalReportsAdapter(
                    manufacturing_path=missing, demo_tenant_id="demo"
                ),
                OperationalReportQuery(
                    "excursions", date(2026, 1, 1), date(2026, 1, 3), limit=1
                ),
            ),
        )
        with patch(
            "app.tools.operational_reports.data_source.sqlite3.connect"
        ) as connect:
            for adapter, query in cases:
                with (
                    self.subTest(query=query),
                    self.assertRaisesRegex(OperationalReportDataError, "unavailable"),
                ):
                    adapter.fetch(query, self.principal)
            connect.assert_not_called()
        self.assertFalse(missing.exists())

    def test_execute_failure_is_closed_and_sanitized(self) -> None:
        real_connect = sqlite3.connect
        connections: list[_ExecuteFailConnection] = []

        def connect(database: str, **kwargs: object) -> _ExecuteFailConnection:
            value = _ExecuteFailConnection(real_connect(database, **kwargs))
            connections.append(value)
            return value

        query = OperationalReportQuery(
            "productivity", date(2026, 1, 1), date(2026, 1, 3)
        )
        with (
            patch(
                "app.tools.operational_reports.data_source.sqlite3.connect",
                side_effect=connect,
            ),
            self.assertRaisesRegex(OperationalReportDataError, "unavailable") as error,
        ):
            self.adapter.fetch(query, self.principal)
        self.assertTrue(connections[0].closed)
        self.assertNotIn("private execution marker", str(error.exception))

    def test_each_query_uses_only_its_related_explicit_store(self) -> None:
        missing = Path(self.directory.name) / "unrelated-missing.db"
        productivity = SQLiteOperationalReportsAdapter(
            equipment_path=self.equipment,
            quality_path=missing,
            manufacturing_path=missing,
            demo_tenant_id="demo",
        )
        defects = SQLiteOperationalReportsAdapter(
            equipment_path=missing,
            quality_path=self.quality,
            manufacturing_path=missing,
            demo_tenant_id="demo",
        )
        excursions = SQLiteOperationalReportsAdapter(
            equipment_path=missing,
            quality_path=missing,
            manufacturing_path=self.manufacturing,
            demo_tenant_id="demo",
        )
        cases = (
            (
                productivity,
                OperationalReportQuery(
                    "productivity", date(2026, 1, 1), date(2026, 1, 3)
                ),
            ),
            (
                defects,
                OperationalReportQuery(
                    "defects", date(2026, 1, 1), date(2026, 1, 3), limit=1
                ),
            ),
            (
                excursions,
                OperationalReportQuery(
                    "excursions", date(2026, 1, 1), date(2026, 1, 3), limit=1
                ),
            ),
        )
        for adapter, query in cases:
            with self.subTest(query=query):
                self.assertTrue(adapter.fetch(query, self.principal).rows)
        self.assertFalse(missing.exists())

    def test_read_only_lifecycle_timeout_close_and_fake_copies(self) -> None:
        real_connect = sqlite3.connect
        spies: list[_ConnectionSpy] = []

        def connect(database: str, **kwargs: object) -> _ConnectionSpy:
            self.assertIn("mode=ro", database)
            self.assertTrue(kwargs["uri"])
            spy = _ConnectionSpy(real_connect(database, **kwargs))
            spies.append(spy)
            return spy

        query = OperationalReportQuery(
            "productivity", date(2026, 1, 1), date(2026, 1, 3)
        )
        with patch(
            "app.tools.operational_reports.data_source.sqlite3.connect",
            side_effect=connect,
        ):
            self.adapter.fetch(query, self.principal)
        self.assertTrue(spies[0].closed)
        executed = "\n".join(spies[0].executed).upper()
        self.assertIn("PRAGMA QUERY_ONLY = ON", executed)
        self.assertNotIn("ATTACH", executed)
        self.assertNotIn("CREATE", executed)
        close_spy: list[_CloseFailConnection] = []

        def close_fail(database: str, **kwargs: object) -> _CloseFailConnection:
            value = _CloseFailConnection(real_connect(database, **kwargs))
            close_spy.append(value)
            return value

        with (
            patch(
                "app.tools.operational_reports.data_source.sqlite3.connect",
                side_effect=close_fail,
            ),
            self.assertRaisesRegex(OperationalReportDataError, "unavailable"),
        ):
            self.adapter.fetch(query, self.principal)
        self.assertTrue(close_spy)
        timeout = _TimeoutConnection()
        timeout_adapter = SQLiteOperationalReportsAdapter(
            equipment_path=self.equipment, demo_tenant_id="demo", query_timeout_ms=1
        )
        with (
            patch(
                "app.tools.operational_reports.data_source.sqlite3.connect",
                return_value=timeout,
            ),
            patch(
                "app.tools.operational_reports.data_source.time.monotonic",
                side_effect=(0.0, 1.0),
            ),
            self.assertRaises(OperationalReportTimeoutError),
        ):
            timeout_adapter.fetch(query, self.principal)
        self.assertTrue(timeout.closed)
        timeout_close = _TimeoutCloseFailConnection()
        with (
            patch(
                "app.tools.operational_reports.data_source.sqlite3.connect",
                return_value=timeout_close,
            ),
            patch(
                "app.tools.operational_reports.data_source.time.monotonic",
                side_effect=(0.0, 1.0),
            ),
            self.assertRaises(OperationalReportTimeoutError),
        ):
            timeout_adapter.fetch(query, self.principal)
        self.assertTrue(timeout_close.closed)
        fixture = {"equipment_id": "CMP-01"}
        fake = FakeOperationalReportsAdapter("demo", {query: (fixture,)})
        fixture["equipment_id"] = "MUTATED"
        self.assertEqual(
            fake.fetch(query, self.principal).rows[0]["equipment_id"], "CMP-01"
        )
        first = fake.fetch(query, self.principal)
        first.rows[0]["equipment_id"] = "CHANGED"
        self.assertEqual(
            fake.fetch(query, self.principal).rows[0]["equipment_id"], "CMP-01"
        )
        self.assertEqual(
            fake.fetch(query, self.principal).source.source_kind, ToolSourceKind.FAKE
        )
        calls = len(fake.calls)
        with self.assertRaisesRegex(OperationalReportDataError, "unavailable"):
            fake.fetch(
                query,
                type(
                    "Other", (), {"tenant_id": "other", "user_id": "u", "roles": ()}
                )(),
            )
        self.assertEqual(len(fake.calls), calls)
        missing_query = OperationalReportQuery(
            "productivity", date(2026, 1, 1), date(2026, 1, 2)
        )
        with self.assertRaisesRegex(
            OperationalReportDataError, "no operational-report fixture"
        ):
            fake.fetch(missing_query, self.principal)

    def test_timeout_configuration_rejects_invalid_values(self) -> None:
        for value in (0, -1, True, "1", None, 10_001):
            with self.subTest(busy=value), self.assertRaises(ValueError):
                SQLiteOperationalReportsAdapter(
                    demo_tenant_id="demo", busy_timeout_ms=value
                )
        for value in (0, -1, True, "1", None, 30_001):
            with self.subTest(query=value), self.assertRaises(ValueError):
                SQLiteOperationalReportsAdapter(
                    demo_tenant_id="demo", query_timeout_ms=value
                )


if __name__ == "__main__":
    unittest.main()
