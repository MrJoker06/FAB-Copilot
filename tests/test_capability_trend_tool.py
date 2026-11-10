"""Weekly capability-trend tool: inputs, read-only SQLite source and handler."""

from __future__ import annotations

import sqlite3
import statistics
import tempfile
import unittest
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import jsonschema

from app.agent_runtime.tools.contracts import ToolExecutionContext, ToolStatus
from app.tools.process_diagnostics.data_source import (
    SQLiteProcessDiagnosticsAdapter,
)
from app.tools.process_diagnostics.binding import PROCESS_CAPABILITY_DEFINITION
from app.tools.process_diagnostics.contracts import ProcessCapabilityInput
from app.tools.capability_trend.contracts import (
    OUTPUT_SCHEMA,
    CapabilityTrendDataError,
    CapabilityTrendInput,
    CapabilityTrendInputError,
    validate_capability_trend_output,
)
from app.demo_data.tool_sources.capability_trend import FakeCapabilityTrendSource
from app.tools.capability_trend.sqlite_source import SQLiteCapabilityTrendSource
from app.tools.capability_trend.tool import (
    CAPABILITY_TREND_DEFINITION,
    create_capability_trend_binding,
)

AS_OF = date(2026, 10, 31)
SPEC = (9.0, 12.0)
# (run_time, process_step, equipment_id, measurement_value)
RUNS = (
    ("2026-09-30 10:00:00", "LITHO", "LITHO-01", 40.0),
    ("2026-10-01 08:00:00", "LITHO", "LITHO-01", 10.0),
    ("2026-10-01 09:00:00", "LITHO", "LITHO-01", 11.0),
    ("2026-10-04 23:00:00", "LITHO", "LITHO-01", 12.0),
    ("2026-10-05 00:30:00", "LITHO", "LITHO-01", 9.0),
    ("2026-10-06 12:00:00", "LITHO", "LITHO-01", 13.0),
    ("2026-10-08 23:00:00", "LITHO", "LITHO-01", 11.0),
    ("2026-10-09 01:00:00", "LITHO", "LITHO-01", 50.0),
    ("2026-10-06 10:00:00", "LITHO", "LITHO-02", 10.0),
    ("2026-10-07 10:00:00", "LITHO", "LITHO-02", 10.0),
    ("2026-10-02 10:00:00", "ETCH", "ETCH-01", 10.5),
)


@dataclass(frozen=True)
class _Principal:
    tenant_id: str = "demo"
    user_id: str = "engineer"
    roles: tuple[str, ...] = ("analyst",)


def _write_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE process_runs (
                run_time TEXT, process_step TEXT, equipment_id TEXT,
                measurement_name TEXT, measurement_value REAL,
                measurement_unit TEXT, spec_lsl REAL, spec_usl REAL)"""
        )
        connection.executemany(
            "INSERT INTO process_runs VALUES (?, ?, ?, 'cd', ?, 'nm', ?, ?)",
            [(*row, *SPEC) for row in RUNS],
        )
    connection.close()


def _expected_cpk(values: list[float]) -> float | None:
    mean, sigma = statistics.fmean(values), statistics.pstdev(values)
    if sigma == 0:
        return None
    return round(min(SPEC[1] - mean, mean - SPEC[0]) / (3 * sigma), 2)


def _call(port: object, arguments: dict[str, object]):
    binding = create_capability_trend_binding(port, today=lambda: AS_OF)
    value = binding.definition.parse(arguments)
    return binding.handler(
        value, ToolExecutionContext(_Principal(), "run", "call", binding.dependencies)
    )


class CapabilityTrendInputTests(unittest.TestCase):
    def test_invalid_inputs_are_rejected(self) -> None:
        for arguments in (
            {"unknown": "x"},
            {"start": None},
            {"start": 20261001},
            {"start": "2026/10/01"},
            {"start": "2026-10-09", "end": "2026-10-01"},
            {"start": "2026-01-01", "end": "2026-10-01"},
            {"process_step": "NOPE"},
            {"equipment_id": "   "},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(
                CapabilityTrendInputError
            ):
                CapabilityTrendInput.from_arguments(arguments).resolve(AS_OF)

    def test_defaults_resolve_to_a_bounded_window(self) -> None:
        query = CapabilityTrendInput.from_arguments({"process_step": "litho"}).resolve(
            AS_OF
        )
        self.assertEqual((query.start, query.end), (date(2026, 8, 3), AS_OF))
        self.assertEqual(query.process_step, "LITHO")


class SQLiteCapabilityTrendTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.path = Path(self._directory.name) / "manufacturing.db"
        _write_database(self.path)
        self.source = SQLiteCapabilityTrendSource(self.path, demo_tenant_id="demo")

    def tearDown(self) -> None:
        self._directory.cleanup()

    def test_weekly_rows_match_independent_statistics(self) -> None:
        result = _call(
            self.source,
            {"start": "2026-10-01", "end": "2026-10-08", "process_step": "LITHO"},
        )
        self.assertIs(result.status, ToolStatus.SUCCEEDED)
        rows = {(row["equipment_id"], row["week_start"]): row for row in result.data}
        self.assertEqual(
            set(rows),
            {
                ("LITHO-01", "2026-09-28"),
                ("LITHO-01", "2026-10-05"),
                ("LITHO-02", "2026-10-05"),
            },
        )
        cases = {
            ("LITHO-01", "2026-09-28"): ([10.0, 11.0, 12.0], "2026-10-01", "2026-10-04"),
            ("LITHO-01", "2026-10-05"): ([9.0, 13.0, 11.0], "2026-10-05", "2026-10-08"),
            ("LITHO-02", "2026-10-05"): ([10.0, 10.0], "2026-10-05", "2026-10-08"),
        }
        for key, (values, first, last) in cases.items():
            with self.subTest(key=key):
                row = rows[key]
                self.assertEqual(row["samples"], len(values))
                self.assertEqual(row["mean_value"], round(statistics.fmean(values), 3))
                self.assertAlmostEqual(
                    row["sigma"], round(statistics.pstdev(values), 3), places=3
                )
                self.assertEqual(row["cpk"], _expected_cpk(values))
                self.assertEqual((row["period_start"], row["period_end"]), (first, last))
        self.assertEqual(result.sources[0].scope.grain, "equipment_week")
        jsonschema.validate(result.data, OUTPUT_SCHEMA)

    def test_equipment_filter_and_source_is_read_only(self) -> None:
        result = _call(
            self.source,
            {"start": "2026-10-01", "end": "2026-10-08", "equipment_id": "LITHO-02"},
        )
        self.assertEqual({row["equipment_id"] for row in result.data}, {"LITHO-02"})
        before = self.path.read_bytes()
        _call(self.source, {"start": "2026-10-01", "end": "2026-10-08"})
        self.assertEqual(self.path.read_bytes(), before)

    def test_unavailable_or_foreign_tenant_fails_explicitly(self) -> None:
        missing = SQLiteCapabilityTrendSource(
            Path(self._directory.name) / "absent.db", demo_tenant_id="demo"
        )
        foreign = SQLiteCapabilityTrendSource(self.path, demo_tenant_id="other")
        for source in (missing, foreign):
            with self.subTest(source=source), self.assertRaises(
                CapabilityTrendDataError
            ):
                _call(source, {"start": "2026-10-01", "end": "2026-10-08"})

    def test_process_capability_output_matches_declared_schema(self) -> None:
        adapter = SQLiteProcessDiagnosticsAdapter(
            self.path, None, demo_tenant_id="demo"
        )
        query = ProcessCapabilityInput.from_arguments(
            {"start": "2026-10-01", "end": "2026-10-08"}
        ).resolve(AS_OF)
        rows = list(adapter.fetch(query, _Principal()).rows)
        self.assertTrue(rows)
        jsonschema.validate(rows, PROCESS_CAPABILITY_DEFINITION.output_schema)
        rows[0]["unexpected"] = 1
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(rows, PROCESS_CAPABILITY_DEFINITION.output_schema)


class CapabilityTrendHandlerTests(unittest.TestCase):
    def _row(self, **changes: object) -> dict[str, object]:
        row: dict[str, object] = {
            "week_start": "2026-10-05",
            "period_start": "2026-10-05",
            "period_end": "2026-10-08",
            "process_step": "LITHO",
            "equipment_id": "LITHO-01",
            "samples": 3,
            "mean_value": 11.0,
            "sigma": 1.633,
            "cpk": 0.2,
            "metric_name": "cd",
            "metric_unit": "nm",
            "spec_lsl": 9.0,
            "spec_usl": 12.0,
        }
        row.update(changes)
        return row

    def _source(self, rows: tuple[dict[str, object], ...]) -> FakeCapabilityTrendSource:
        query = CapabilityTrendInput.from_arguments(
            {"start": "2026-10-01", "end": "2026-10-08", "process_step": "LITHO"}
        ).resolve(AS_OF)
        return FakeCapabilityTrendSource("demo", {query: rows})

    def test_rows_outside_scope_or_contract_are_rejected(self) -> None:
        arguments = {"start": "2026-10-01", "end": "2026-10-08", "process_step": "LITHO"}
        for rows in (
            (self._row(process_step="ETCH"),),
            (self._row(period_end="2026-10-09"),),
            (self._row(week_start="2026-10-06"),),
            (self._row(), self._row()),
            (self._row(samples=0),),
            ({**self._row(), "extra": 1},),
        ):
            with self.subTest(rows=rows), self.assertRaises(CapabilityTrendDataError):
                _call(self._source(rows), arguments)

    def test_valid_fixture_rows_pass_validator_and_schema(self) -> None:
        rows = [self._row(), self._row(equipment_id="LITHO-02", sigma=0.0, cpk=None)]
        self.assertIs(validate_capability_trend_output(rows), rows)
        jsonschema.validate(rows, CAPABILITY_TREND_DEFINITION.output_schema)


if __name__ == "__main__":
    unittest.main()
