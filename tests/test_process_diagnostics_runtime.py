"""End-to-end checks for the explicitly assembled diagnostics demo."""

from __future__ import annotations

import asyncio
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.bootstrap import diagnostics_demo
from app.manufacturing.process_diagnostics.contracts import DiagnosticsDataError

_CAPABILITY = "get_process_capability"
_SENSORS = "get_sensor_summary"
_CAPABILITY_ARGUMENTS = '{"process_step":"CMP"}'
_SENSOR_ARGUMENTS = (
    '{"process_step":"CMP","equipment_id":"CMP-01","signal_name":"pressure"}'
)


def _run(*arguments: str) -> dict[str, object]:
    parsed = diagnostics_demo._parser().parse_args(list(arguments))
    return asyncio.run(diagnostics_demo._run(parsed))


def _manufacturing_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE process_runs (
                process_step TEXT, equipment_id TEXT, run_time TEXT,
                measurement_value REAL, measurement_name TEXT, measurement_unit TEXT,
                spec_lsl REAL, spec_usl REAL)"""
        )
        connection.executemany(
            "INSERT INTO process_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("CMP", "CMP-01", "2026-10-20", 10.0, "thickness", "nm", 9.0, 12.0),
                ("CMP", "CMP-01", "2026-10-21", 11.0, "thickness", "nm", 9.0, 12.0),
            ],
        )


def _equipment_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE sensor_readings (
                process_step TEXT, equipment_id TEXT, signal_name TEXT,
                signal_unit TEXT, sample_time TEXT, is_missing INTEGER,
                is_outlier INTEGER, signal_value REAL)"""
        )
        connection.executemany(
            "INSERT INTO sensor_readings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("CMP", "CMP-01", "pressure", "kPa", "2026-10-20", 0, 0, 10.0),
                ("CMP", "CMP-01", "pressure", "kPa", "2026-10-21", 0, 1, 11.0),
                ("CMP", "CMP-02", "pressure", "kPa", "2026-10-21", 0, 0, 30.0),
            ],
        )


class ProcessDiagnosticsRuntimeTests(unittest.TestCase):
    def _assert_common_success(
        self, payload: dict[str, object], mode: str, tool: str, source_ref: str
    ) -> dict[str, object]:
        result = payload["typed_results"][0]
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["tool"], tool)
        self.assertEqual(result["error"], None)
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(payload["guard"]["total_calls"], 1)
        self.assertEqual(payload["guard"]["per_tool_calls"], {tool: 1})
        self.assertEqual(
            payload["plan"]["budget"]["per_tool_limits"],
            {_CAPABILITY: 1, _SENSORS: 1},
        )
        self.assertEqual(payload["observations"][0]["source_ref"], "TOOL:S01")
        self.assertIn(source_ref, payload["sources"])
        if mode == "ready":
            self.assertEqual(payload["model_tool_selection_calls"], 0)
            self.assertEqual(payload["model_response_calls"], 0)
        else:
            self.assertEqual(payload["model_tool_selection_calls"], 1)
            self.assertEqual(payload["model_response_calls"], 2)
            self.assertEqual(
                payload["tool_messages"][0]["tool_call_id"], "diagnostics-tool-1"
            )
        return result

    def test_fake_native_tools_run_through_ready_and_loop(self) -> None:
        for mode in ("ready", "loop"):
            for tool, arguments, grain in (
                (_CAPABILITY, _CAPABILITY_ARGUMENTS, "equipment_distribution"),
                (_SENSORS, _SENSOR_ARGUMENTS, "equipment_signal"),
            ):
                with self.subTest(mode=mode, tool=tool):
                    payload = _run(
                        "--mode", mode, "--tool", tool, "--arguments", arguments
                    )
                    result = self._assert_common_success(
                        payload, mode, tool, "fake:process-diagnostics"
                    )
                    self.assertTrue(result["data"])
                    self.assertEqual(
                        payload["sources"]["fake:process-diagnostics"]["scope"][
                            "grain"
                        ],
                        grain,
                    )

    def test_sqlite_native_tools_preserve_data_and_joint_source_scope(self) -> None:
        with TemporaryDirectory() as raw:
            base = Path(raw)
            manufacturing, equipment = base / "manufacturing.db", base / "equipment.db"
            _manufacturing_db(manufacturing)
            _equipment_db(equipment)
            for mode in ("ready", "loop"):
                for tool, arguments in (
                    (_CAPABILITY, _CAPABILITY_ARGUMENTS),
                    (_SENSORS, _SENSOR_ARGUMENTS),
                ):
                    with self.subTest(mode=mode, tool=tool):
                        selected_path = (
                            ("--manufacturing-db", str(manufacturing))
                            if tool == _CAPABILITY
                            else ("--equipment-db", str(equipment))
                        )
                        payload = _run(
                            "--mode",
                            mode,
                            "--adapter",
                            "sqlite",
                            "--tool",
                            tool,
                            "--arguments",
                            arguments,
                            *selected_path,
                        )
                        kind = "capability" if tool == _CAPABILITY else "sensors"
                        result = self._assert_common_success(
                            payload,
                            mode,
                            tool,
                            f"sqlite:process-diagnostics:{kind}",
                        )
                        source = payload["sources"][
                            f"sqlite:process-diagnostics:{kind}"
                        ]
                        self.assertEqual(source["source_kind"], "sqlite")
                        self.assertEqual(source["scope"]["tenant_id"], "demo")
                        self.assertEqual(source["scope"]["start"], "2026-07-27")
                        self.assertEqual(source["scope"]["end"], "2026-10-24")
                        if tool == _CAPABILITY:
                            self.assertEqual(
                                source["scope"]["grain"], "equipment_distribution"
                            )
                            self.assertEqual(source["scope"]["process_steps"], ["CMP"])
                            self.assertEqual(source["scope"]["equipment_ids"], [])
                            self.assertEqual(
                                result["data"],
                                [
                                    {
                                        "process_step": "CMP",
                                        "equipment_id": "CMP-01",
                                        "samples": 2,
                                        "mean_value": 10.5,
                                        "sigma": 0.5,
                                        "min_value": 10.0,
                                        "max_value": 11.0,
                                        "cpk": 1.0,
                                        "metric_name": "thickness",
                                        "metric_unit": "nm",
                                        "spec_lsl": 9.0,
                                        "spec_usl": 12.0,
                                    }
                                ],
                            )
                        else:
                            observation = payload["observations"][0]["arguments"]
                            self.assertEqual(
                                source["scope"]["grain"], "equipment_signal"
                            )
                            self.assertEqual(source["scope"]["process_steps"], ["CMP"])
                            self.assertEqual(
                                source["scope"]["equipment_ids"], ["CMP-01"]
                            )
                            self.assertEqual(observation["process_step"], "CMP")
                            self.assertEqual(observation["equipment_id"], "CMP-01")
                            self.assertEqual(observation["signal_name"], "pressure")
                            self.assertEqual(
                                result["data"],
                                [
                                    {
                                        "process_step": "CMP",
                                        "equipment_id": "CMP-01",
                                        "signal_name": "pressure",
                                        "signal_unit": "kPa",
                                        "samples": 2,
                                        "missing_samples": 0,
                                        "flagged_outliers": 1,
                                        "mean_value": 10.5,
                                        "min_value": 10.0,
                                        "max_value": 11.0,
                                    }
                                ],
                            )

    def test_denied_role_and_sql_never_reach_a_data_port(self) -> None:
        class CountingPort:
            calls = 0

            def fetch(self, query: object, principal: object) -> object:
                del query, principal
                self.calls += 1
                raise AssertionError("denied calls must not reach the data port")

        port = CountingPort()
        with patch.object(diagnostics_demo, "_adapter", return_value=(port, "fake")):
            for mode in ("ready", "loop"):
                with self.subTest(mode=mode, rejection="role"):
                    role_payload = _run("--mode", mode, "--role", "viewer")
                    self.assertEqual(
                        role_payload["typed_results"][0]["status"], "denied"
                    )
                with self.subTest(mode=mode, rejection="unknown_sql"):
                    sql_payload = _run(
                        "--mode",
                        mode,
                        "--tool",
                        "query_manufacturing_data",
                        "--arguments",
                        '{"sql":"select secret from manufacturing"}',
                    )
                    result = sql_payload["typed_results"][0]
                    self.assertEqual(result["status"], "denied")
                    self.assertEqual(result["state"], "not_started")
                    self.assertEqual(sql_payload["guard"]["total_calls"], 0)
                    self.assertNotIn("secret", str(sql_payload))
                with self.subTest(mode=mode, rejection="native_sql_argument"):
                    native_payload = _run(
                        "--mode",
                        mode,
                        "--tool",
                        _CAPABILITY,
                        "--arguments",
                        '{"process_step":"CMP","sql":"select secret"}',
                    )
                    result = native_payload["typed_results"][0]
                    self.assertEqual(result["status"], "invalid_arguments")
                    self.assertEqual(result["state"], "not_started")
                    self.assertEqual(native_payload["guard"]["total_calls"], 0)
                    self.assertNotIn("secret", str(native_payload))
        self.assertEqual(port.calls, 0)

    def test_data_port_fault_has_no_fake_or_sqlite_fallback(self) -> None:
        class BrokenPort:
            calls = 0

            def fetch(self, query: object, principal: object) -> object:
                del query, principal
                self.calls += 1
                raise DiagnosticsDataError("source unavailable")

        port = BrokenPort()
        with patch.object(diagnostics_demo, "_adapter", return_value=(port, "fake")):
            payload = _run("--mode", "loop", "--arguments", _CAPABILITY_ARGUMENTS)
        self.assertEqual(payload["typed_results"][0]["status"], "failed")
        self.assertEqual(payload["typed_results"][0]["state"], "completed")
        self.assertEqual(port.calls, 1)
        self.assertEqual(payload["guard"]["per_tool_calls"], {_CAPABILITY: 1})


if __name__ == "__main__":
    unittest.main()
