"""Ready and Loop checks for operational report bindings."""

from __future__ import annotations

import asyncio
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.bootstrap import operational_reports_demo
from app.demo_data.tool_sources.operational_reports import (
    FakeOperationalReportsAdapter,
)
from app.tools.operational_reports.data_source import (
    SQLiteOperationalReportsAdapter,
)
from app.tools.operational_reports.contracts import OperationalReportDataError


def _run(*values: str) -> dict[str, object]:
    return asyncio.run(
        operational_reports_demo._run(
            operational_reports_demo._parser().parse_args(values)
        )
    )


class OperationalRuntimeTests(unittest.TestCase):
    def test_empty_sqlite_result_is_successful_empty_list(self) -> None:
        with TemporaryDirectory() as raw:
            database = Path(raw) / "equipment.db"
            with sqlite3.connect(database) as conn:
                conn.execute(
                    "CREATE TABLE equipment_state_intervals (equipment_id TEXT,start_time TEXT,duration_minutes REAL,semi_e10_state TEXT)"
                )
            for mode in ("ready", "loop"):
                payload = _run(
                    "--mode",
                    mode,
                    "--adapter",
                    "sqlite",
                    "--equipment-db",
                    str(database),
                    "--tool",
                    "get_equipment_productivity",
                    "--arguments",
                    '{"start":"2026-01-01","end":"2026-01-01"}',
                )
                result = payload["typed_results"][0]
                self.assertEqual(
                    (
                        result["status"],
                        result["data"],
                        result["row_count"],
                        payload["guard"]["total_calls"],
                    ),
                    ("succeeded", [], 0, 1),
                )

    def test_sqlite_ready_loop_use_only_the_related_store(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            equipment, quality, manufacturing = (
                root / "e.db",
                root / "q.db",
                root / "m.db",
            )
            with sqlite3.connect(equipment) as conn:
                conn.execute(
                    "CREATE TABLE equipment_state_intervals (equipment_id TEXT,start_time TEXT,duration_minutes REAL,semi_e10_state TEXT)"
                )
                conn.executemany(
                    "INSERT INTO equipment_state_intervals VALUES (?,?,?,?)",
                    [
                        ("CMP-01", "2026-10-20", 8, "Productive"),
                        ("CMP-01", "2026-10-20", 2, "Scheduled Downtime"),
                    ],
                )
            with sqlite3.connect(quality) as conn:
                conn.execute(
                    "CREATE TABLE defect_records (defect_type TEXT,process_step TEXT,count INTEGER,lot_id TEXT,detected_time TEXT)"
                )
                conn.executemany(
                    "INSERT INTO defect_records VALUES (?,?,?,?,?)",
                    [
                        ("Particle", "CMP", 4, "L1", "2026-10-20"),
                        ("Scratch", "CMP", 1, "L2", "2026-10-20"),
                    ],
                )
            with sqlite3.connect(manufacturing) as conn:
                conn.execute(
                    "CREATE TABLE process_runs (run_time TEXT,lot_id TEXT,process_step TEXT,equipment_id TEXT,excursion_code TEXT,thickness_nm REAL,uniformity_pct REAL,defect_density REAL,measurement_name TEXT,measurement_value REAL,measurement_unit TEXT,spec_lsl REAL,spec_usl REAL)"
                )
                conn.execute(
                    "INSERT INTO process_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "2026-10-20",
                        "L1",
                        "CMP",
                        "CMP-01",
                        "E1",
                        10,
                        1,
                        0.1,
                        "thickness",
                        10,
                        "nm",
                        9,
                        11,
                    ),
                )
                conn.executemany(
                    "INSERT INTO process_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            "2026-10-21",
                            "L2",
                            "ETCH",
                            "CMP-01",
                            "E2",
                            9,
                            1,
                            0.2,
                            "thickness",
                            9,
                            "nm",
                            8,
                            10,
                        ),
                        (
                            "2026-10-21",
                            "L3",
                            "CMP",
                            "CMP-02",
                            "E3",
                            8,
                            1,
                            0.3,
                            "thickness",
                            8,
                            "nm",
                            7,
                            9,
                        ),
                    ],
                )
            cases = (
                (
                    "get_equipment_productivity",
                    '{"equipment_id":"cmp-01"}',
                    "--equipment-db",
                    equipment,
                    [
                        {
                            "equipment_id": "CMP-01",
                            "recorded_minutes": 10.0,
                            "productive_minutes": 8.0,
                            "productive_pct": 80.0,
                            "unscheduled_down_minutes": 0.0,
                            "scheduled_down_minutes": 2.0,
                        }
                    ],
                ),
                (
                    "get_defect_pareto",
                    '{"process_step":"CMP","limit":1}',
                    "--quality-db",
                    quality,
                    [
                        {
                            "defect_type": "Particle",
                            "process_steps": "CMP",
                            "defect_count": 4,
                            "affected_lots": 1,
                            "share_pct": 80.0,
                        }
                    ],
                ),
                (
                    "get_recent_excursions",
                    '{"process_step":"CMP","equipment_id":"cmp-01","limit":1}',
                    "--manufacturing-db",
                    manufacturing,
                    [
                        {
                            "run_time": "2026-10-20",
                            "lot_id": "L1",
                            "process_step": "CMP",
                            "equipment_id": "CMP-01",
                            "excursion_code": "E1",
                            "thickness_nm": 10.0,
                            "uniformity_pct": 1.0,
                            "defect_density": 0.1,
                            "measurement_name": "thickness",
                            "measurement_value": 10.0,
                            "measurement_unit": "nm",
                            "spec_lsl": 9.0,
                            "spec_usl": 11.0,
                        }
                    ],
                ),
            )
            for mode in ("ready", "loop"):
                for tool, arguments, pathflag, path, expected in cases:
                    with self.subTest(mode=mode, tool=tool):
                        payload = _run(
                            "--mode",
                            mode,
                            "--adapter",
                            "sqlite",
                            pathflag,
                            str(path),
                            "--tool",
                            tool,
                            "--arguments",
                            arguments,
                        )
                        result = payload["typed_results"][0]
                        self.assertEqual(
                            (result["status"], result["data"], result["row_count"]),
                            ("succeeded", expected, 1),
                        )
                        self.assertEqual(
                            (
                                payload["guard"]["total_calls"],
                                payload["observations"][0]["source_ref"],
                            ),
                            (1, "TOOL:S01"),
                        )
                        self.assertEqual(result["version"], "1.0.0")
                        self.assertEqual(
                            payload["model_tool_selection_calls"],
                            0 if mode == "ready" else 1,
                        )
                        self.assertEqual(
                            payload["model_response_calls"], 0 if mode == "ready" else 2
                        )
                        source = payload["sources"][
                            f"sqlite:operational-reports:{ {'get_equipment_productivity': 'productivity', 'get_defect_pareto': 'defects', 'get_recent_excursions': 'excursions'}[tool] }"
                        ]
                        self.assertEqual(source["source_kind"], "sqlite")
                        scope = source["scope"]
                        if tool == "get_equipment_productivity":
                            self.assertEqual(
                                (scope["process_steps"], scope["equipment_ids"]),
                                ([], ["CMP-01"]),
                            )
                            self.assertEqual(
                                payload["observations"][0]["arguments"],
                                {
                                    "start": "2026-07-27",
                                    "end": "2026-10-24",
                                    "equipment_id": "CMP-01",
                                },
                            )
                        elif tool == "get_defect_pareto":
                            self.assertEqual(
                                (scope["process_steps"], scope["equipment_ids"]),
                                (["CMP"], []),
                            )
                            self.assertEqual(
                                payload["observations"][0]["arguments"],
                                {
                                    "start": "2026-07-27",
                                    "end": "2026-10-24",
                                    "process_step": "CMP",
                                    "limit": 1,
                                },
                            )
                        else:
                            self.assertEqual(
                                (scope["process_steps"], scope["equipment_ids"]),
                                (["CMP"], ["CMP-01"]),
                            )
                            self.assertEqual(
                                payload["observations"][0]["arguments"],
                                {
                                    "start": "2026-07-27",
                                    "end": "2026-10-24",
                                    "process_step": "CMP",
                                    "equipment_id": "CMP-01",
                                    "limit": 1,
                                },
                            )

    def test_fake_ready_loop_full_values_and_effective_scope(self) -> None:
        cases = (
            (
                "get_equipment_productivity",
                '{"process_step":"ETCH","equipment_id":"cmp-01"}',
                [
                    {
                        "equipment_id": "CMP-01",
                        "recorded_minutes": 10.0,
                        "productive_minutes": 8.0,
                        "productive_pct": 80.0,
                        "unscheduled_down_minutes": 1.0,
                        "scheduled_down_minutes": 1.0,
                    }
                ],
                [],
                ["CMP-01"],
                "equipment_productivity",
            ),
            (
                "get_defect_pareto",
                '{"process_step":"CMP","limit":1}',
                [
                    {
                        "defect_type": "Particle",
                        "process_steps": "CMP",
                        "defect_count": 4,
                        "affected_lots": 2,
                        "share_pct": 100.0,
                    }
                ],
                ["CMP"],
                [],
                "defect_type",
            ),
            (
                "get_recent_excursions",
                '{"process_step":"CMP","equipment_id":"cmp-01","limit":1}',
                [
                    {
                        "run_time": "2026-10-24",
                        "lot_id": "LOT-001",
                        "process_step": "CMP",
                        "equipment_id": "CMP-01",
                        "excursion_code": "E001",
                        "thickness_nm": 10.0,
                        "uniformity_pct": 1.0,
                        "defect_density": 0.1,
                        "measurement_name": "thickness",
                        "measurement_value": 10.0,
                        "measurement_unit": "nm",
                        "spec_lsl": 9.0,
                        "spec_usl": 11.0,
                    }
                ],
                ["CMP"],
                ["CMP-01"],
                "process_run",
            ),
        )
        for mode in ("ready", "loop"):
            for tool, arguments, expected, processes, equipment, grain in cases:
                with self.subTest(mode=mode, tool=tool):
                    payload = _run(
                        "--mode", mode, "--tool", tool, "--arguments", arguments
                    )
                    result = payload["typed_results"][0]
                    self.assertEqual(
                        (
                            result["status"],
                            result["version"],
                            result["execution_state"],
                            result["data"],
                        ),
                        ("succeeded", "1.0.0", "completed", expected),
                    )
                    self.assertEqual(
                        (
                            result["row_count"],
                            payload["guard"]["total_calls"],
                            payload["observations"][0]["source_ref"],
                        ),
                        (1, 1, "TOOL:S01"),
                    )
                    scope = payload["sources"]["fake:operational-reports"]["scope"]
                    self.assertEqual(
                        (
                            scope["process_steps"],
                            scope["equipment_ids"],
                            scope["grain"],
                        ),
                        (processes, equipment, grain),
                    )
                    self.assertEqual(
                        payload["model_tool_selection_calls"],
                        0 if mode == "ready" else 1,
                    )
                    self.assertEqual(
                        payload["model_response_calls"], 0 if mode == "ready" else 2
                    )

    def test_rejections_and_source_fault_do_not_query(self) -> None:
        calls: list[str] = []
        fake = FakeOperationalReportsAdapter.fetch
        sqlite = SQLiteOperationalReportsAdapter.fetch

        def fake_fetch(self, query, principal):
            calls.append("fake")
            return fake(self, query, principal)

        def sqlite_fetch(self, query, principal):
            calls.append("sqlite")
            return sqlite(self, query, principal)

        cases = (
            (
                "query_manufacturing_data",
                '{"sql":"secret"}',
                "denied",
                "authorization",
                (),
            ),
            (
                "get_defect_pareto",
                '{"sql":"secret"}',
                "invalid_arguments",
                "validation",
                (),
            ),
            (
                "get_defect_pareto",
                '{"limit":99}',
                "invalid_arguments",
                "validation",
                (),
            ),
            (
                "get_defect_pareto",
                '{"process_step":"bad"}',
                "invalid_arguments",
                "validation",
                (),
            ),
            (
                "get_defect_pareto",
                "{}",
                "denied",
                "authorization",
                ("--role", "viewer"),
            ),
            (
                "get_defect_pareto",
                "{}",
                "denied",
                "authorization",
                ("--tenant-id", "other"),
            ),
        )
        with TemporaryDirectory() as raw:
            databases = {
                "equipment": Path(raw) / "equipment.db",
                "quality": Path(raw) / "quality.db",
                "manufacturing": Path(raw) / "manufacturing.db",
            }
            for database in databases.values():
                with sqlite3.connect(database):
                    pass
            with (
                patch.object(FakeOperationalReportsAdapter, "fetch", fake_fetch),
                patch.object(SQLiteOperationalReportsAdapter, "fetch", sqlite_fetch),
            ):
                for adapter, adapter_args in (
                    ("fake", ()),
                    (
                        "sqlite",
                        (
                            "--adapter",
                            "sqlite",
                            "--equipment-db",
                            str(databases["equipment"]),
                            "--quality-db",
                            str(databases["quality"]),
                            "--manufacturing-db",
                            str(databases["manufacturing"]),
                        ),
                    ),
                ):
                    for mode in ("ready", "loop"):
                        for tool, args, status, kind, extra in cases:
                            with self.subTest(
                                adapter=adapter, mode=mode, tool=tool, args=args
                            ):
                                payload = _run(
                                    "--mode",
                                    mode,
                                    "--tool",
                                    tool,
                                    "--arguments",
                                    args,
                                    *adapter_args,
                                    *extra,
                                )
                                result = payload["typed_results"][0]
                                self.assertEqual(
                                    (
                                        result["status"],
                                        result["error"]["kind"],
                                        result["state"],
                                        payload["guard"]["total_calls"],
                                    ),
                                    (status, kind, "not_started", 0),
                                )
                                self.assertNotIn("secret", str(payload))
        self.assertEqual(calls, [])

    def test_source_fault_and_loop_message_requirement(self) -> None:
        class Broken:
            calls = 0

            def fetch(self, query, principal):
                self.calls += 1
                raise OperationalReportDataError("secret source")

        port = Broken()
        with patch.object(operational_reports_demo, "_fake", return_value=port):
            for mode in ("ready", "loop"):
                payload = _run(
                    "--mode", mode, "--tool", "get_defect_pareto", "--arguments", "{}"
                )
                result = payload["typed_results"][0]
                self.assertEqual(
                    (result["status"], result["error"]["kind"]),
                    ("failed", "data_source"),
                )
                self.assertNotIn("secret", str(payload))
        self.assertEqual(port.calls, 2)
        model = operational_reports_demo._LoopModel("get_defect_pareto", "{}")
        request = operational_reports_demo.ModelRequest("x", ())
        asyncio.run(model.complete(request, object()))
        with self.assertRaises(AssertionError):
            asyncio.run(model.complete(request, object()))


if __name__ == "__main__":
    unittest.main()
