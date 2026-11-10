from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime.tools.contracts import ToolExecutionContext, ToolSourceKind
from app.core.sqlite_support import install_sqlite_functions
from app.integrations.manufacturing.fake_named_queries import FakeNamedQueryAdapter
from app.integrations.manufacturing.sqlite_named_queries import SQLiteNamedQueryAdapter
from app.manufacturing.named_queries.contracts import (
    EquipmentEventsInput,
    EquipmentExcursionsInput,
    LotQueryInput,
    NamedQuery,
    NamedQueryDataError,
    NamedQueryTimeoutError,
    ProductYieldInput,
)
from app.manufacturing.named_queries.handler import (
    NamedQueryDependencies,
    named_query_handler,
)
from app.planning_runtime.queries import _manufacturing_queries


class Principal:
    tenant_id = "demo"
    user_id = "analyst"
    roles = ("analyst",)


class OtherPrincipal(Principal):
    tenant_id = "other"


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


class _ExecuteFailConnection(_TimeoutConnection):
    def execute(self, sql: str, parameters: object = ()) -> _TimeoutConnection:
        if sql.lstrip().upper().startswith("SELECT"):
            raise sqlite3.OperationalError("private execution marker")
        return super().execute(sql, parameters)


class _ConnectionSpy:
    def __init__(
        self, connection: sqlite3.Connection, *, fail_close: bool = False
    ) -> None:
        object.__setattr__(self, "connection", connection)
        object.__setattr__(self, "fail_close", fail_close)
        object.__setattr__(self, "executed", [])

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
        self.connection.close()
        if self.fail_close:
            raise sqlite3.OperationalError("private close detail")


class NamedQueryAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.manufacturing = root / "manufacturing.db"
        self.equipment = root / "equipment.db"
        self.quality = root / "quality.db"
        self._make_manufacturing()
        self._make_equipment()
        self._make_quality()
        self.principal = Principal()
        self.adapter = SQLiteNamedQueryAdapter(
            manufacturing_path=self.manufacturing,
            equipment_path=self.equipment,
            quality_path=self.quality,
            demo_tenant_id="demo",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _make_manufacturing(self) -> None:
        with sqlite3.connect(self.manufacturing) as con:
            con.execute("""CREATE TABLE lots (lot_id TEXT, product TEXT, technology_nm INTEGER,
                route TEXT, priority TEXT, start_time TEXT, complete_time TEXT, status TEXT,
                wafer_count INTEGER, good_wafers INTEGER, yield_rate REAL, cycle_time_hours REAL,
                hold_hours REAL)""")
            con.executemany(
                "INSERT INTO lots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "L1",
                        "P1",
                        28,
                        "R",
                        "Normal",
                        "2020-01-01",
                        "2026-01-01T23:59",
                        "done",
                        10,
                        8,
                        0.8,
                        2.0,
                        0.0,
                    ),
                    (
                        "L2",
                        "P1",
                        28,
                        "R",
                        "Hot",
                        "2020-01-01",
                        "2026-01-02",
                        "done",
                        20,
                        20,
                        1.0,
                        3.0,
                        0.0,
                    ),
                    (
                        "L3",
                        "P2",
                        14,
                        "R",
                        "Normal",
                        "2020-01-01",
                        None,
                        "active",
                        25,
                        0,
                        0.0,
                        0.0,
                        0.0,
                    ),
                ],
            )
            con.execute("""CREATE TABLE process_runs (lot_id TEXT, operation_seq INTEGER, layer_name TEXT,
                process_step TEXT, equipment_id TEXT, chamber TEXT, recipe TEXT, run_time TEXT,
                queue_hours REAL, rework_flag INTEGER, excursion_code TEXT, measurement_name TEXT,
                measurement_value REAL, measurement_unit TEXT, spec_lsl REAL, spec_usl REAL)""")
            con.executemany(
                "INSERT INTO process_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        "L1",
                        2,
                        "M2",
                        "CMP",
                        "CMP-01",
                        "C",
                        "r",
                        "2020-01-02",
                        1.0,
                        0,
                        "",
                        "m",
                        -1.0,
                        "nm",
                        None,
                        1.0,
                    ),
                    (
                        "L1",
                        1,
                        "M1",
                        "ETCH",
                        "ETCH-01",
                        "C",
                        "r",
                        "2020-01-01",
                        2.0,
                        1,
                        "E1",
                        "m",
                        1.0,
                        "nm",
                        0.0,
                        2.0,
                    ),
                    (
                        "L2",
                        1,
                        "M1",
                        "CMP",
                        "CMP-01",
                        "C",
                        "r",
                        "2026-01-02",
                        2.0,
                        0,
                        "E2",
                        "m",
                        2.0,
                        "nm",
                        0.0,
                        3.0,
                    ),
                    (
                        "L3",
                        1,
                        "M1",
                        "CMP",
                        "OTHER",
                        "C",
                        "r",
                        "2026-01-02",
                        2.0,
                        0,
                        "E3",
                        "m",
                        3.0,
                        "nm",
                        0.0,
                        3.0,
                    ),
                    (
                        "L4",
                        1,
                        "M1",
                        "ETCH",
                        "CMP-01",
                        "C",
                        "r",
                        "2026-01-02",
                        0.0,
                        0,
                        "E4",
                        "m",
                        4.0,
                        "nm",
                        0.0,
                        5.0,
                    ),
                ],
            )

    def _make_equipment(self) -> None:
        with sqlite3.connect(self.equipment) as con:
            con.execute("""CREATE TABLE equipment_events (equipment_id TEXT, event_time TEXT,
                event_type TEXT, duration_minutes REAL, severity TEXT, reason TEXT)""")
            con.executemany(
                "INSERT INTO equipment_events VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("CMP-01", "2026-01-02", "alarm", 2.0, "high", "r"),
                    ("OTHER", "2026-01-01", "alarm", 1.0, "low", "r"),
                    ("CMP-01", "2026-01-03", "outside", 1.0, "low", "r"),
                ]
                + [
                    ("CAP", "2026-01-02", "alarm", 1.0, "low", str(index))
                    for index in range(101)
                ],
            )

    def _make_quality(self) -> None:
        with sqlite3.connect(self.quality) as con:
            con.execute("""CREATE TABLE defect_records (lot_id TEXT, detected_time TEXT,
                process_step TEXT, defect_type TEXT, count INTEGER, disposition TEXT)""")
            con.execute(
                "INSERT INTO defect_records VALUES ('L1', '2020-01-01', 'CMP', 'D', 2, 'hold')"
            )
            con.execute("""CREATE TABLE wafer_maps (lot_id TEXT, wafer_no INTEGER, detected_time TEXT,
                process_step TEXT, equipment_id TEXT, pattern_class TEXT, tested_dies INTEGER,
                failed_dies INTEGER)""")
            con.executemany(
                "INSERT INTO wafer_maps VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("L1", 2, "2020-01-02", "CMP", "CMP-01", "ring", 10, 1),
                    ("L1", 1, "2020-01-01", "CMP", "CMP-01", "edge", 10, 0),
                ],
            )

    @staticmethod
    def _legacy_reference(path: Path, sql: str) -> list[dict[str, object]]:
        """Independent read-only oracle with the retired legacy 100-row cap."""
        statement = sql.strip().rstrip(";")
        if not re.search(r"(?i)\blimit\s+\d+\b", statement):
            statement += " LIMIT 100"
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        install_sqlite_functions(connection)
        try:
            connection.execute("PRAGMA query_only = ON")
            return [dict(row) for row in connection.execute(statement).fetchmany(100)]
        finally:
            connection.close()

    def _handler_data(self, input_value: object, kind: str) -> list[dict[str, object]]:
        context = ToolExecutionContext(
            self.principal,
            "run",
            "call",
            NamedQueryDependencies(self.adapter, kind, date(2026, 1, 2)),
        )
        return named_query_handler(input_value, context).data  # type: ignore[arg-type, return-value]

    def test_all_eight_match_actual_legacy_planner_sql_and_handler(self) -> None:
        cases = (
            (
                "YLD-02",
                0,
                self.manufacturing,
                "product_yield",
                ProductYieldInput("2026-01-01", "2026-01-02", "P1"),
                "product",
                ("P1",),
                (),
                (),
                {},
            ),
            (
                "EQP-03",
                0,
                self.equipment,
                "equipment_events",
                EquipmentEventsInput("2026-01-01", "2026-01-02", "CMP-01"),
                "all",
                (),
                (),
                ("CMP-01",),
                {},
            ),
            (
                "YLD-02",
                0,
                self.manufacturing,
                "product_yield",
                ProductYieldInput("2026-01-01", "2026-01-02", "p1"),
                "product",
                ("p1",),
                (),
                (),
                {},
            ),
            (
                "EQP-03",
                0,
                self.equipment,
                "equipment_events",
                EquipmentEventsInput("2026-01-01", "2026-01-02", "CAP"),
                "all",
                (),
                (),
                ("CAP",),
                {},
            ),
            (
                "EQP-04",
                0,
                self.manufacturing,
                "equipment_excursions",
                EquipmentExcursionsInput("2026-01-01", "2026-01-02", "CMP"),
                "all",
                (),
                ("CMP",),
                (),
                {},
            ),
            (
                "EQP-04",
                0,
                self.manufacturing,
                "equipment_excursions",
                EquipmentExcursionsInput("2026-01-01", "2026-01-02", None, "CMP-01"),
                "all",
                (),
                (),
                ("CMP-01",),
                {},
            ),
            (
                "EQP-04",
                0,
                self.manufacturing,
                "equipment_excursions",
                EquipmentExcursionsInput("2026-01-01", "2026-01-02", "CMP", "CMP-01"),
                "all",
                (),
                ("CMP",),
                ("CMP-01",),
                {},
            ),
            (
                "LOT-01",
                0,
                self.manufacturing,
                "lot_identity",
                LotQueryInput("L1"),
                "all",
                (),
                (),
                (),
                {"lot_id": "L1"},
            ),
            (
                "LOT-02",
                0,
                self.manufacturing,
                "lot_process_history",
                LotQueryInput("L1"),
                "all",
                (),
                (),
                (),
                {"lot_id": "L1"},
            ),
            (
                "LOT-03",
                0,
                self.manufacturing,
                "lot_excursions",
                LotQueryInput("L1"),
                "all",
                (),
                (),
                (),
                {"lot_id": "L1"},
            ),
            (
                "LOT-03",
                1,
                self.quality,
                "lot_defects",
                LotQueryInput("L1"),
                "all",
                (),
                (),
                (),
                {"lot_id": "L1"},
            ),
            (
                "LOT-03",
                2,
                self.quality,
                "lot_wafer_maps",
                LotQueryInput("L1"),
                "all",
                (),
                (),
                (),
                {"lot_id": "L1"},
            ),
        )
        for (
            evidence,
            index,
            source,
            kind,
            input_value,
            scope_type,
            ids,
            steps,
            equipment,
            resolved,
        ) in cases:
            with self.subTest(kind=kind):
                route = SimpleNamespace(
                    time_range=SimpleNamespace(start="2026-01-01", end="2026-01-02"),
                    scope_resolution=SimpleNamespace(
                        scope_type=scope_type, resolved_ids=ids
                    ),
                    process_steps=steps,
                    equipment_ids=equipment,
                )
                sql = _manufacturing_queries(evidence, route, resolved)[index][1]
                reference = self._legacy_reference(source, sql)
                query = input_value.resolve(kind, date(2026, 1, 2))
                self.assertEqual(
                    self.adapter.fetch(query, self.principal).rows, tuple(reference)
                )
                self.assertEqual(self._handler_data(input_value, kind), reference)
                if kind == "equipment_events" and query.equipment_id == "CAP":
                    self.assertEqual(len(reference), 100)
                if kind == "lot_identity":
                    self.assertLessEqual(len(reference), 10)

    def test_all_eight_fixed_queries_and_scopes(self) -> None:
        queries = (
            NamedQuery(
                "product_yield", date(2026, 1, 1), date(2026, 1, 2), product="P1"
            ),
            NamedQuery(
                "equipment_events",
                date(2026, 1, 1),
                date(2026, 1, 2),
                equipment_id="CMP-01",
            ),
            NamedQuery(
                "equipment_excursions",
                date(2026, 1, 1),
                date(2026, 1, 2),
                process_step="CMP",
                equipment_id="CMP-01",
            ),
            NamedQuery("lot_identity", lot_id="L1"),
            NamedQuery("lot_process_history", lot_id="L1"),
            NamedQuery("lot_excursions", lot_id="L1"),
            NamedQuery("lot_defects", lot_id="L1"),
            NamedQuery("lot_wafer_maps", lot_id="L1"),
        )
        expected_columns = {
            "product_yield": (
                "product",
                "technology_nm",
                "lots",
                "wafers",
                "yield_pct",
            ),
            "equipment_events": (
                "equipment_id",
                "event_time",
                "event_type",
                "duration_minutes",
                "severity",
                "reason",
            ),
            "equipment_excursions": (
                "lot_id",
                "run_time",
                "process_step",
                "equipment_id",
                "excursion_code",
                "measurement_name",
                "measurement_value",
                "measurement_unit",
                "spec_lsl",
                "spec_usl",
            ),
        }
        for query in queries:
            with self.subTest(kind=query.kind):
                snapshot = self.adapter.fetch(query, self.principal)
                self.assertEqual(snapshot.query, query)
                self.assertEqual(snapshot.source.source_kind, ToolSourceKind.SQLITE)
                self.assertEqual(
                    snapshot.source.scope.lot_ids, ("L1",) if query.lot_id else ()
                )
                if query.kind in expected_columns:
                    self.assertEqual(
                        tuple(snapshot.rows[0]), expected_columns[query.kind]
                    )
        self.assertEqual(
            self.adapter.fetch(queries[0], self.principal).rows[0]["yield_pct"], 93.33
        )
        self.assertEqual(
            self.adapter.fetch(queries[4], self.principal).rows[0]["operation_seq"], 1
        )
        self.assertEqual(
            self.adapter.fetch(queries[5], self.principal).rows[0]["excursion_code"],
            "E1",
        )
        self.assertEqual(
            [
                r["wafer_no"]
                for r in self.adapter.fetch(queries[7], self.principal).rows
            ],
            [1, 2],
        )

    def test_dates_are_exclusive_at_next_day_lot_history_is_all_time_and_filters_bind(
        self,
    ) -> None:
        event = NamedQuery(
            "equipment_events",
            date(2026, 1, 2),
            date(2026, 1, 2),
            equipment_id="CMP-01",
        )
        self.assertEqual(len(self.adapter.fetch(event, self.principal).rows), 1)
        excursion = NamedQuery(
            "equipment_excursions",
            date(2026, 1, 1),
            date(2026, 1, 2),
            process_step="CMP",
            equipment_id="CMP-01",
        )
        self.assertEqual(
            [r["lot_id"] for r in self.adapter.fetch(excursion, self.principal).rows],
            ["L2"],
        )
        self.assertEqual(
            len(
                self.adapter.fetch(
                    NamedQuery("lot_process_history", lot_id="L1"), self.principal
                ).rows
            ),
            2,
        )
        injection = NamedQuery("lot_identity", lot_id="L1' OR 1=1 --")
        self.assertEqual(self.adapter.fetch(injection, self.principal).rows, ())

    def test_fake_is_exact_copied_and_checks_tenant_before_calls(self) -> None:
        query = NamedQuery("lot_identity", lot_id="L1")
        fixture = ({"lot_id": "L1"},)
        fake = FakeNamedQueryAdapter("demo", {query: fixture})
        with self.assertRaises(NamedQueryDataError):
            fake.fetch(query, OtherPrincipal())
        self.assertEqual(fake.calls, [])
        result = fake.fetch(query, self.principal)
        result.rows[0]["lot_id"] = "changed"
        self.assertEqual(fake.fetch(query, self.principal).rows, fixture)
        self.assertEqual(result.source.source_ref, "fake:named-query/lot_identity")

    def test_selected_missing_source_does_not_create_or_open_unrelated_database(
        self,
    ) -> None:
        missing = SQLiteNamedQueryAdapter(
            manufacturing_path=self.manufacturing,
            equipment_path=self.equipment,
            quality_path=Path(self.directory.name) / "missing.db",
            demo_tenant_id="demo",
        )
        with self.assertRaises(NamedQueryDataError):
            missing.fetch(NamedQuery("lot_defects", lot_id="L1"), self.principal)
        self.assertFalse((Path(self.directory.name) / "missing.db").exists())

    def test_timeout_wins_over_close_failure_and_errors_are_sanitized(self) -> None:
        adapter = SQLiteNamedQueryAdapter(
            manufacturing_path=self.manufacturing,
            demo_tenant_id="demo",
            query_timeout_ms=1,
        )
        connection = _TimeoutCloseFailConnection()
        with (
            patch(
                "app.integrations.manufacturing.sqlite_named_queries.sqlite3.connect",
                return_value=connection,
            ),
            patch(
                "app.integrations.manufacturing.sqlite_named_queries.time.monotonic",
                side_effect=(0.0, 1.0),
            ),
            self.assertRaises(NamedQueryTimeoutError) as raised,
        ):
            adapter.fetch(NamedQuery("lot_identity", lot_id="L1"), self.principal)
        self.assertNotIn("private", str(raised.exception))
        self.assertTrue(connection.closed)

    def test_execute_and_builtin_timeout_errors_are_typed_and_sanitized(self) -> None:
        adapter = SQLiteNamedQueryAdapter(
            manufacturing_path=self.manufacturing, demo_tenant_id="demo"
        )
        execute_error = _ExecuteFailConnection()
        with (
            patch(
                "app.integrations.manufacturing.sqlite_named_queries.sqlite3.connect",
                return_value=execute_error,
            ),
            self.assertRaises(NamedQueryDataError) as raised,
        ):
            adapter.fetch(NamedQuery("lot_identity", lot_id="L1"), self.principal)
        self.assertNotIn("private", str(raised.exception))
        self.assertTrue(execute_error.closed)
        with (
            patch(
                "app.integrations.manufacturing.sqlite_named_queries.sqlite3.connect",
                side_effect=TimeoutError("private timeout marker"),
            ),
            self.assertRaises(NamedQueryTimeoutError) as raised,
        ):
            adapter.fetch(NamedQuery("lot_identity", lot_id="L1"), self.principal)
        self.assertNotIn("private", str(raised.exception))

    def test_readonly_uri_query_only_and_plain_close_error_are_sanitized(self) -> None:
        original_connect = sqlite3.connect
        captured: dict[str, object] = {}

        def connect(*args: object, **kwargs: object) -> _ConnectionSpy:
            captured.update(kwargs)
            captured["uri"] = args[0]
            spy = _ConnectionSpy(original_connect(*args, **kwargs), fail_close=True)
            captured["connection"] = spy
            return spy

        with (
            patch(
                "app.integrations.manufacturing.sqlite_named_queries.sqlite3.connect",
                side_effect=connect,
            ),
            self.assertRaises(NamedQueryDataError) as raised,
        ):
            self.adapter.fetch(NamedQuery("lot_identity", lot_id="L1"), self.principal)
        self.assertIn("mode=ro", str(captured["uri"]))
        self.assertTrue(captured["uri"])
        self.assertIn("PRAGMA query_only = ON", captured["connection"].executed)
        self.assertNotIn("private", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
