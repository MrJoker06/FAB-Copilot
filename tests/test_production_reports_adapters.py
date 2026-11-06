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
from app.integrations.manufacturing.fake_production_reports import (
    FakeProductionReportsAdapter,
)
from app.integrations.manufacturing.sqlite_production_reports import (
    SQLiteProductionReportsAdapter,
)
from app.manufacturing import reports
from app.manufacturing.production_reports.contracts import (
    ProductionReportDataError,
    ProductionReportQuery,
    ProductionReportTimeoutError,
)


class Principal:
    tenant_id = "demo"
    user_id = "analyst"
    roles = ("analyst",)


class _ConnectionSpy:
    """Delegate to SQLite while recording the adapter's connection lifecycle."""

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


class _TimeoutConnection:
    """Connection fake which invokes its progress handler before the report SQL."""

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


class ProductionReportAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "manufacturing.db"
        self._make_database()
        self.adapter = SQLiteProductionReportsAdapter(self.path, demo_tenant_id="demo")
        self.principal = Principal()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _make_database(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE lots (
                    complete_time TEXT, start_time TEXT, wafer_count INTEGER,
                    good_wafers INTEGER, cycle_time_hours REAL, hold_hours REAL,
                    status TEXT, product TEXT)"""
            )
            connection.execute(
                """CREATE TABLE process_runs (
                    run_time TEXT, process_step TEXT, equipment_id TEXT,
                    pass_flag INTEGER, excursion_code TEXT)"""
            )
            connection.executemany(
                "INSERT INTO lots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "2026-01-01T00:00",
                        "2025-12-31",
                        100,
                        60,
                        10.0,
                        2.0,
                        "Hold",
                        "P1",
                    ),
                    ("2026-01-02", "2026-01-01", 1, 1, 30.0, 1.0, "Completed", "P1"),
                    (None, "2026-01-03T23:59", 0, 0, 20.0, 3.0, "Completed", "P2"),
                    (
                        "2026-01-04T00:00",
                        "2026-01-03",
                        9,
                        9,
                        4.0,
                        0.0,
                        "Completed",
                        "p1",
                    ),
                    (
                        "2026-01-05",
                        "2026-01-04",
                        10,
                        8,
                        8.0,
                        4.0,
                        "Completed",
                        "P1' OR 1=1 --",
                    ),
                ],
            )
            connection.executemany(
                "INSERT INTO process_runs VALUES (?, ?, ?, ?, ?)",
                [
                    ("2026-01-01T23:59", "CMP", "CMP-01", 1, "E1"),
                    ("2026-01-02", "CMP", "CMP-01", None, None),
                    ("2026-01-03", "CMP", "CMP-01", 0, "E2"),
                    ("2026-01-03", "CMP", "CMP-02", 1, None),
                    ("2026-01-04T00:00", "ETCH", "ETCH-01", 1, "E3"),
                ],
            )

    @contextmanager
    def _legacy_session(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        install_sqlite_functions(connection)
        try:
            yield connection
        finally:
            connection.close()

    def _legacy(self, callback):
        with patch.object(reports, "db_session", self._legacy_session):
            return callback()

    def test_all_three_queries_exactly_match_legacy_sql(self) -> None:
        queries = (
            (
                ProductionReportQuery("overview", date(2026, 1, 1), date(2026, 1, 3)),
                lambda: reports.fab_overview("2026-01-01", "2026-01-03"),
            ),
            (
                ProductionReportQuery(
                    "yield", date(2026, 1, 1), date(2026, 1, 5), product="P1"
                ),
                lambda: reports.yield_trend("2026-01-01", "2026-01-05", "P1"),
            ),
            (
                ProductionReportQuery(
                    "pass_rate",
                    date(2026, 1, 1),
                    date(2026, 1, 3),
                    "CMP",
                    "CMP-01",
                ),
                lambda: reports.process_pass_rate(
                    "2026-01-01", "2026-01-03", "CMP", "CMP-01"
                ),
            ),
        )
        for query, legacy in queries:
            with self.subTest(query=query):
                actual = self.adapter.fetch(query, self.principal).data
                expected = self._legacy(legacy)
                self.assertEqual(
                    actual, expected if isinstance(actual, dict) else tuple(expected)
                )

    def test_overview_keeps_coalesce_dates_final_day_empty_and_zero_wafer_cases(
        self,
    ) -> None:
        final_day = ProductionReportQuery(
            "overview", date(2026, 1, 3), date(2026, 1, 3)
        )
        result = self.adapter.fetch(final_day, self.principal).data
        self.assertEqual(result["lots"], 1)
        self.assertEqual(result["wafers"], 0)
        self.assertIsNone(result["yield_pct"])
        self.assertEqual(result["excursions"], 1)
        self.assertEqual((result["start"], result["end"]), ("2026-01-03", "2026-01-03"))

        empty = self.adapter.fetch(
            ProductionReportQuery("overview", date(2026, 2, 1), date(2026, 2, 1)),
            self.principal,
        ).data
        self.assertEqual(empty["lots"], 0)
        self.assertIsNone(empty["held_lots"])
        self.assertEqual(empty["excursions"], 0)
        for name in (
            "wafers",
            "good_wafers",
            "yield_pct",
            "avg_cycle_hours",
            "avg_hold_hours",
        ):
            with self.subTest(name=name):
                self.assertIsNone(empty[name])

    def test_yield_is_weighted_uses_complete_time_and_binds_exact_product(self) -> None:
        weighted = self.adapter.fetch(
            ProductionReportQuery(
                "yield", date(2026, 1, 1), date(2026, 1, 2), product="P1"
            ),
            self.principal,
        ).data
        self.assertEqual(len(weighted), 1)
        self.assertEqual(weighted[0]["yield_pct"], 60.4)
        self.assertNotEqual(weighted[0]["yield_pct"], 80.0)
        self.assertEqual(weighted[0]["lots"], 2)

        exact_case = self.adapter.fetch(
            ProductionReportQuery(
                "yield", date(2026, 1, 1), date(2026, 1, 5), product="p1"
            ),
            self.principal,
        ).data
        self.assertEqual(tuple(row["lots"] for row in exact_case), (1,))
        injected = self.adapter.fetch(
            ProductionReportQuery(
                "yield", date(2026, 1, 1), date(2026, 1, 5), product="P1' OR 1=1 --"
            ),
            self.principal,
        ).data
        self.assertEqual(sum(row["lots"] for row in injected), 1)
        self.assertEqual(injected[0]["yield_pct"], 80.0)

    def test_yield_week_grouping_matches_legacy_across_year_boundary(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO lots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("2025-12-31", "2025-12-31", 10, 5, 5.0, 0.0, "Completed", "P1"),
            )
        query = ProductionReportQuery(
            "yield", date(2025, 12, 31), date(2026, 1, 2), product="P1"
        )
        actual = self.adapter.fetch(query, self.principal).data
        expected = self._legacy(
            lambda: reports.yield_trend("2025-12-31", "2026-01-02", "P1")
        )
        self.assertEqual(actual, tuple(expected))
        self.assertGreaterEqual(len(actual), 1)

    def test_pass_rate_keeps_null_average_and_joint_equipment_filter(self) -> None:
        exact = self.adapter.fetch(
            ProductionReportQuery(
                "pass_rate", date(2026, 1, 1), date(2026, 1, 3), "CMP", "CMP-01"
            ),
            self.principal,
        ).data
        self.assertEqual(
            exact,
            (
                {
                    "process_step": "CMP",
                    "equipment_id": "CMP-01",
                    "runs": 3,
                    "passed_runs": 1,
                    "pass_pct": 50.0,
                },
            ),
        )
        self.assertNotEqual(
            exact[0]["pass_pct"], 100.0 * exact[0]["passed_runs"] / exact[0]["runs"]
        )
        grouped = self.adapter.fetch(
            ProductionReportQuery(
                "pass_rate", date(2026, 1, 1), date(2026, 1, 3), "CMP"
            ),
            self.principal,
        ).data
        self.assertEqual(grouped[0]["equipment_id"], None)
        self.assertEqual(grouped[0]["runs"], 4)
        self.assertEqual(grouped[0]["passed_runs"], 2)
        self.assertEqual(grouped[0]["pass_pct"], 66.67)
        empty = self.adapter.fetch(
            ProductionReportQuery(
                "pass_rate", date(2026, 2, 1), date(2026, 2, 1), "CMP"
            ),
            self.principal,
        ).data
        self.assertEqual(empty, ())

    def test_tenant_missing_and_permission_errors_are_sanitized_before_or_during_connect(
        self,
    ) -> None:
        query = ProductionReportQuery("overview", date(2026, 1, 1), date(2026, 1, 3))
        with patch(
            "app.integrations.manufacturing.sqlite_production_reports.sqlite3.connect"
        ) as connect:
            with self.assertRaisesRegex(ProductionReportDataError, "unavailable"):
                self.adapter.fetch(
                    query,
                    type(
                        "Other", (), {"tenant_id": "other", "user_id": "u", "roles": ()}
                    )(),
                )
            connect.assert_not_called()

        missing = Path(self.directory.name) / "does-not-exist.db"
        missing_adapter = SQLiteProductionReportsAdapter(missing, demo_tenant_id="demo")
        with self.assertRaisesRegex(ProductionReportDataError, "unavailable") as error:
            missing_adapter.fetch(query, self.principal)
        self.assertFalse(missing.exists())
        self.assertNotIn(str(missing), str(error.exception))
        with (
            patch.object(Path, "is_file", side_effect=PermissionError("/private/path")),
            self.assertRaisesRegex(ProductionReportDataError, "unavailable") as error,
        ):
            self.adapter.fetch(query, self.principal)
        self.assertNotIn("private", str(error.exception))

    def test_read_only_query_only_no_attach_and_close_lifecycle(self) -> None:
        real_connect = sqlite3.connect
        spies: list[_ConnectionSpy] = []

        def connect(database: str, **kwargs: object) -> _ConnectionSpy:
            self.assertTrue(database.startswith("file:"), database)
            self.assertIn("mode=ro", database)
            self.assertTrue(kwargs["uri"])
            spy = _ConnectionSpy(real_connect(database, **kwargs))
            spies.append(spy)
            return spy

        query = ProductionReportQuery("overview", date(2026, 1, 1), date(2026, 1, 3))
        with patch(
            "app.integrations.manufacturing.sqlite_production_reports.sqlite3.connect",
            side_effect=connect,
        ):
            self.adapter.fetch(query, self.principal)
        self.assertEqual(len(spies), 1)
        self.assertTrue(spies[0].closed)
        executed = "\n".join(spies[0].executed).upper()
        self.assertIn("PRAGMA QUERY_ONLY = ON", executed)
        self.assertNotIn("ATTACH", executed)
        self.assertNotIn("CREATE", executed)
        self.assertNotIn("INITIAL", executed)

    def test_close_and_progress_timeout_are_sanitized(self) -> None:
        query = ProductionReportQuery("overview", date(2026, 1, 1), date(2026, 1, 3))
        real_connect = sqlite3.connect
        close_spy: list[_CloseFailConnection] = []

        def close_fail_connect(database: str, **kwargs: object) -> _CloseFailConnection:
            value = _CloseFailConnection(real_connect(database, **kwargs))
            close_spy.append(value)
            return value

        with (
            patch(
                "app.integrations.manufacturing.sqlite_production_reports.sqlite3.connect",
                side_effect=close_fail_connect,
            ),
            self.assertRaisesRegex(ProductionReportDataError, "unavailable") as error,
        ):
            self.adapter.fetch(query, self.principal)
        self.assertNotIn("private", str(error.exception))
        self.assertEqual(len(close_spy), 1)

        timeout = _TimeoutConnection()
        timeout_adapter = SQLiteProductionReportsAdapter(
            self.path, demo_tenant_id="demo", query_timeout_ms=1
        )
        with (
            patch(
                "app.integrations.manufacturing.sqlite_production_reports.sqlite3.connect",
                return_value=timeout,
            ),
            patch(
                "app.integrations.manufacturing.sqlite_production_reports.time.monotonic",
                side_effect=(0.0, 1.0),
            ),
            self.assertRaises(ProductionReportTimeoutError),
        ):
            timeout_adapter.fetch(query, self.principal)
        self.assertTrue(timeout.closed)

    def test_fake_is_exact_tenant_scoped_and_returns_copies(self) -> None:
        query = ProductionReportQuery(
            "yield", date(2026, 1, 1), date(2026, 1, 1), product="P1"
        )
        fake = FakeProductionReportsAdapter(
            "demo",
            {
                query: (
                    {
                        "period": "2026-00",
                        "week_start": "2026-01-01",
                        "lots": 1,
                        "yield_pct": 60.0,
                        "cycle_hours": 10.0,
                    },
                )
            },
        )
        first = fake.fetch(query, self.principal)
        first.data[0]["lots"] = 99
        second = fake.fetch(query, self.principal)
        self.assertEqual(second.data[0]["lots"], 1)
        self.assertEqual(second.source.source_kind, ToolSourceKind.FAKE)
        self.assertEqual(fake.calls, [query, query])
        with self.assertRaisesRegex(ProductionReportDataError, "unavailable"):
            fake.fetch(
                query,
                type(
                    "Other", (), {"tenant_id": "other", "user_id": "u", "roles": ()}
                )(),
            )

    def test_timeout_configuration_rejects_malformed_values(self) -> None:
        for value in (0, -1, 10_001, True, "1", None):
            with self.subTest(busy_timeout_ms=value), self.assertRaises(ValueError):
                SQLiteProductionReportsAdapter(
                    self.path, demo_tenant_id="demo", busy_timeout_ms=value
                )
        for value in (0, -1, 30_001, True, "1", None):
            with self.subTest(query_timeout_ms=value), self.assertRaises(ValueError):
                SQLiteProductionReportsAdapter(
                    self.path, demo_tenant_id="demo", query_timeout_ms=value
                )
        SQLiteProductionReportsAdapter(
            self.path,
            demo_tenant_id="demo",
            busy_timeout_ms=10_000,
            query_timeout_ms=30_000,
        )


if __name__ == "__main__":
    unittest.main()
