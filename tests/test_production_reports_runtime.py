"""Ready and Loop acceptance tests for the native production-report slice."""

from __future__ import annotations

import asyncio
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.bootstrap import production_reports_demo
from app.demo_data.tool_sources.production_reports import (
    FakeProductionReportsAdapter,
)
from app.tools.production_reports.data_source import (
    SQLiteProductionReportsAdapter,
)
from app.tools.production_reports.contracts import ProductionReportDataError

_OVERVIEW = "get_fab_overview"
_YIELD = "get_yield_trend"
_PASS = "get_process_pass_rate"
_TOOLS = (_OVERVIEW, _YIELD, _PASS)


def _run(*arguments: str) -> dict[str, object]:
    parsed = production_reports_demo._parser().parse_args(list(arguments))
    return asyncio.run(production_reports_demo._run(parsed))


def _manufacturing_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
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
                ("2026-10-20", "2026-10-19", 10, 9, 12.0, 1.0, "Hold", "P1"),
                ("2026-10-21", "2026-10-20", 1, 0, 24.0, 2.0, "Completed", "P1"),
            ],
        )
        connection.executemany(
            "INSERT INTO process_runs VALUES (?, ?, ?, ?, ?)",
            [
                ("2026-10-20", "CMP", "CMP-01", 1, "E1"),
                ("2026-10-21", "CMP", "CMP-01", None, None),
                ("2026-10-21", "CMP", "CMP-02", 0, None),
            ],
        )


class ProductionReportsRuntimeTests(unittest.TestCase):
    def _assert_success(
        self,
        payload: dict[str, object],
        mode: str,
        tool: str,
        source_ref: str,
        row_count: int,
        grain: str,
        *,
        process: str | None = None,
        equipment: str | None = None,
        start: str = "2026-07-27",
        end: str = "2026-10-24",
    ) -> dict[str, object]:
        result = payload["typed_results"][0]
        self.assertEqual(result["tool"], tool)
        self.assertEqual(result["version"], "1.0.0")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["execution_state"], "completed")
        self.assertEqual(result["error"], None)
        self.assertEqual(result["row_count"], row_count)
        self.assertEqual(payload["guard"]["total_calls"], 1)
        self.assertEqual(payload["guard"]["per_tool_calls"], {tool: 1})
        self.assertEqual(payload["observations"][0]["source_ref"], "TOOL:S01")
        self.assertIn(source_ref, payload["sources"])
        scope = payload["sources"][source_ref]["scope"]
        self.assertEqual(scope["tenant_id"], "demo")
        self.assertEqual(scope["start"], start)
        self.assertEqual(scope["end"], end)
        self.assertEqual(scope["grain"], grain)
        self.assertEqual(scope["process_steps"], [] if process is None else [process])
        self.assertEqual(
            scope["equipment_ids"], [] if equipment is None else [equipment]
        )
        self.assertEqual(
            payload["plan"]["budget"]["per_tool_limits"], {name: 1 for name in _TOOLS}
        )
        if mode == "ready":
            self.assertEqual(payload["model_tool_selection_calls"], 0)
            self.assertEqual(payload["model_response_calls"], 0)
        else:
            self.assertEqual(payload["model_tool_selection_calls"], 1)
            self.assertEqual(payload["model_response_calls"], 2)
            self.assertEqual(
                payload["tool_messages"][0]["tool_call_id"], "production-tool-1"
            )
            self.assertEqual(
                payload["final_response"],
                "Fixed production report Loop fixture completed.",
            )
        return result

    def test_all_tools_fake_run_through_ready_and_loop(self) -> None:
        cases = (
            (
                _OVERVIEW,
                "{}",
                1,
                "fab_overview",
                None,
                None,
                {
                    "lots": 1,
                    "wafers": 10,
                    "good_wafers": 9,
                    "yield_pct": 90.0,
                    "avg_cycle_hours": 1.0,
                    "avg_hold_hours": 0.0,
                    "held_lots": 0,
                    "excursions": 0,
                    "start": "2026-07-27",
                    "end": "2026-10-24",
                },
                {"start": "2026-07-27", "end": "2026-10-24"},
            ),
            (
                _YIELD,
                '{"product":"P1"}',
                1,
                "weekly_yield",
                None,
                None,
                [
                    {
                        "period": "2026-30",
                        "week_start": "2026-07-27",
                        "lots": 1,
                        "yield_pct": 90.0,
                        "cycle_hours": 1.0,
                    }
                ],
                {"product": "P1", "start": "2026-07-27", "end": "2026-10-24"},
            ),
            (
                _PASS,
                '{"process_step":"CMP"}',
                1,
                "process_pass_rate",
                "CMP",
                None,
                [
                    {
                        "process_step": "CMP",
                        "equipment_id": None,
                        "runs": 1,
                        "passed_runs": 1,
                        "pass_pct": 100.0,
                    }
                ],
                {"start": "2026-07-27", "end": "2026-10-24", "process_step": "CMP"},
            ),
        )
        for mode in ("ready", "loop"):
            for (
                tool,
                arguments,
                rows,
                grain,
                process,
                equipment,
                expected,
                observed,
            ) in cases:
                with self.subTest(mode=mode, tool=tool):
                    payload = _run(
                        "--mode", mode, "--tool", tool, "--arguments", arguments
                    )
                    result = self._assert_success(
                        payload,
                        mode,
                        tool,
                        "fake:production-reports",
                        rows,
                        grain,
                        process=process,
                        equipment=equipment,
                    )
                    self.assertEqual(result["data"], expected)
                    self.assertEqual(payload["observations"][0]["arguments"], observed)

    def test_all_tools_sqlite_run_through_ready_and_loop(self) -> None:
        with TemporaryDirectory() as raw:
            database = Path(raw) / "manufacturing.db"
            _manufacturing_db(database)
            cases = (
                (
                    _OVERVIEW,
                    "{}",
                    1,
                    "fab_overview",
                    None,
                    None,
                    "overview",
                    {
                        "lots": 2,
                        "wafers": 11,
                        "good_wafers": 9,
                        "yield_pct": 81.82,
                        "avg_cycle_hours": 18.0,
                        "avg_hold_hours": 1.5,
                        "held_lots": 1,
                        "excursions": 1,
                        "start": "2026-07-27",
                        "end": "2026-10-24",
                    },
                    {"start": "2026-07-27", "end": "2026-10-24"},
                ),
                (
                    _YIELD,
                    '{"product":"P1"}',
                    1,
                    "weekly_yield",
                    None,
                    None,
                    "yield",
                    [
                        {
                            "period": "2026-42",
                            "week_start": "2026-10-20",
                            "lots": 2,
                            "yield_pct": 81.82,
                            "cycle_hours": 18.0,
                        }
                    ],
                    {"product": "P1", "start": "2026-07-27", "end": "2026-10-24"},
                ),
                (
                    _PASS,
                    '{"process_step":"cmp","equipment_id":"cmp-01"}',
                    1,
                    "process_pass_rate",
                    "CMP",
                    "CMP-01",
                    "pass_rate",
                    [
                        {
                            "process_step": "CMP",
                            "equipment_id": "CMP-01",
                            "runs": 2,
                            "passed_runs": 1,
                            "pass_pct": 100.0,
                        }
                    ],
                    {
                        "start": "2026-07-27",
                        "end": "2026-10-24",
                        "process_step": "CMP",
                        "equipment_id": "CMP-01",
                    },
                ),
            )
            for mode in ("ready", "loop"):
                for (
                    tool,
                    arguments,
                    rows,
                    grain,
                    process,
                    equipment,
                    kind,
                    expected,
                    observed,
                ) in cases:
                    with self.subTest(mode=mode, tool=tool):
                        payload = _run(
                            "--mode",
                            mode,
                            "--adapter",
                            "sqlite",
                            "--manufacturing-db",
                            str(database),
                            "--tool",
                            tool,
                            "--arguments",
                            arguments,
                        )
                        result = self._assert_success(
                            payload,
                            mode,
                            tool,
                            f"sqlite:production-reports:{kind}",
                            rows,
                            grain,
                            process=process,
                            equipment=equipment,
                        )
                        self.assertEqual(result["data"], expected)
                        self.assertEqual(
                            payload["observations"][0]["arguments"], observed
                        )

    def test_empty_sqlite_overview_is_a_successful_null_result(self) -> None:
        with TemporaryDirectory() as raw:
            database = Path(raw) / "manufacturing.db"
            _manufacturing_db(database)
            for mode in ("ready", "loop"):
                with self.subTest(mode=mode):
                    payload = _run(
                        "--mode",
                        mode,
                        "--adapter",
                        "sqlite",
                        "--manufacturing-db",
                        str(database),
                        "--tool",
                        _OVERVIEW,
                        "--arguments",
                        '{"start":"2026-01-01","end":"2026-01-01"}',
                    )
                    result = self._assert_success(
                        payload,
                        mode,
                        _OVERVIEW,
                        "sqlite:production-reports:overview",
                        1,
                        "fab_overview",
                        start="2026-01-01",
                        end="2026-01-01",
                    )
                    self.assertEqual(
                        result["data"],
                        {
                            "lots": 0,
                            "wafers": None,
                            "good_wafers": None,
                            "yield_pct": None,
                            "avg_cycle_hours": None,
                            "avg_hold_hours": None,
                            "held_lots": None,
                            "excursions": 0,
                            "start": "2026-01-01",
                            "end": "2026-01-01",
                        },
                    )

    def test_rejected_calls_never_reach_fake_or_sqlite_port(self) -> None:
        original_fake = FakeProductionReportsAdapter.fetch
        original_sqlite = SQLiteProductionReportsAdapter.fetch
        calls: list[str] = []

        def fake_fetch(self, query, principal):
            calls.append("fake")
            return original_fake(self, query, principal)

        def sqlite_fetch(self, query, principal):
            calls.append("sqlite")
            return original_sqlite(self, query, principal)

        with TemporaryDirectory() as raw:
            database = Path(raw) / "manufacturing.db"
            _manufacturing_db(database)
            with (
                patch.object(FakeProductionReportsAdapter, "fetch", fake_fetch),
                patch.object(SQLiteProductionReportsAdapter, "fetch", sqlite_fetch),
            ):
                adapter_modes = (
                    ("ready", ()),
                    ("loop", ()),
                    (
                        "ready",
                        ("--adapter", "sqlite", "--manufacturing-db", str(database)),
                    ),
                    (
                        "loop",
                        ("--adapter", "sqlite", "--manufacturing-db", str(database)),
                    ),
                )
                rejections = (
                    (
                        "query_manufacturing_data",
                        '{"sql":"select secret"}',
                        (),
                        "denied",
                        "authorization",
                    ),
                    (
                        _OVERVIEW,
                        '{"sql":"select secret"}',
                        (),
                        "invalid_arguments",
                        "validation",
                    ),
                    (
                        _PASS,
                        '{"process_step":"invalid"}',
                        (),
                        "invalid_arguments",
                        "validation",
                    ),
                    (_OVERVIEW, "{}", ("--role", "viewer"), "denied", "authorization"),
                    (
                        _OVERVIEW,
                        "{}",
                        ("--tenant-id", "other"),
                        "denied",
                        "authorization",
                    ),
                )
                for mode, adapter_args in adapter_modes:
                    for tool, arguments, extra, status, error_kind in rejections:
                        with self.subTest(
                            mode=mode, tool=tool, arguments=arguments, extra=extra
                        ):
                            payload = _run(
                                "--mode",
                                mode,
                                "--tool",
                                tool,
                                "--arguments",
                                arguments,
                                *adapter_args,
                                *extra,
                            )
                            result = payload["typed_results"][0]
                            self.assertEqual(result["status"], status)
                            self.assertEqual(result["error"]["kind"], error_kind)
                            self.assertEqual(result["state"], "not_started")
                            self.assertEqual(payload["guard"]["total_calls"], 0)
                            self.assertNotIn("secret", str(payload))
        self.assertEqual(calls, [])

    def test_source_fault_never_falls_back(self) -> None:
        class BrokenPort:
            calls = 0

            def fetch(self, query: object, principal: object) -> object:
                del query, principal
                self.calls += 1
                raise ProductionReportDataError("marker source fault")

        port = BrokenPort()
        with patch.object(production_reports_demo, "_fake", return_value=port):
            for mode in ("ready", "loop"):
                with self.subTest(mode=mode):
                    payload = _run(
                        "--mode", mode, "--tool", _OVERVIEW, "--arguments", "{}"
                    )
                    result = payload["typed_results"][0]
                    self.assertEqual(result["status"], "failed")
                    self.assertEqual(result["error"]["kind"], "data_source")
                    self.assertNotIn("marker", str(payload))
        self.assertEqual(port.calls, 2)

    def test_loop_fixture_requires_matching_tool_message(self) -> None:
        model = production_reports_demo._LoopModel(_OVERVIEW, "{}")
        request = production_reports_demo.ModelRequest("fixture-call", ())
        context = object()
        asyncio.run(model.complete(request, context))  # type: ignore[arg-type]
        with self.assertRaisesRegex(AssertionError, "tool message"):
            asyncio.run(model.complete(request, context))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
