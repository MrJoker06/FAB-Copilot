"""Independent result and scope acceptance through the actual Ready/Loop executors."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import unittest
from unittest.mock import patch

from app.agent_runtime.execution.runtime_contracts import ModelRequest
from app.bootstrap import named_queries_demo as demo
from app.demo_data.tool_sources.named_queries import FakeNamedQueryAdapter
from app.tools.named_queries.data_source import SQLiteNamedQueryAdapter
from app.tools.named_queries.contracts import (
    NamedQueryDataError,
    NamedQueryTimeoutError,
)
from tests import test_named_queries_adapters as adapter_tests

CASES = (
    (
        "get_product_yield_breakdown",
        {"start": "2026-01-01", "end": "2026-01-02", "product": "P1"},
        "product_yield",
        "product",
    ),
    (
        "get_equipment_event_timeline",
        {"start": "2026-01-01", "end": "2026-01-02", "equipment_id": "CMP-01"},
        "equipment_events",
        "event",
    ),
    (
        "get_equipment_excursion_history",
        {
            "start": "2026-01-01",
            "end": "2026-01-02",
            "process_step": "CMP",
            "equipment_id": "CMP-01",
        },
        "equipment_excursions",
        "event",
    ),
    ("get_lot_identity", {"lot_id": "L1"}, "lot_identity", "lot"),
    ("get_lot_process_history", {"lot_id": "L1"}, "lot_process_history", "process_run"),
    ("get_lot_excursion_history", {"lot_id": "L1"}, "lot_excursions", "event"),
    ("get_lot_defect_history", {"lot_id": "L1"}, "lot_defects", "defect_event"),
    ("get_lot_wafer_map_patterns", {"lot_id": "L1"}, "lot_wafer_maps", "wafer"),
)


def records(columns: str, *values: tuple) -> list[dict]:
    """Materialize literal acceptance tables without calling production helpers."""
    return [dict(zip(columns.split(), row, strict=True)) for row in values]


FAKE_ROWS = {
    "product_yield": records(
        "product technology_nm lots wafers yield_pct", ("P1", 7, 2, 50, 96.0)
    ),
    "equipment_events": records(
        "equipment_id event_time event_type duration_minutes severity reason",
        ("CMP-01", "2026-01-02", "maintenance", 15.0, "low", "scheduled"),
    ),
    "equipment_excursions": records(
        "lot_id run_time process_step equipment_id excursion_code measurement_name measurement_value measurement_unit spec_lsl spec_usl",
        (
            "LOT-001",
            "2026-01-02",
            "CMP",
            "CMP-01",
            "E001",
            "thickness",
            10.0,
            "nm",
            9.0,
            11.0,
        ),
    ),
    "lot_identity": records(
        "lot_id product technology_nm route priority start_time complete_time status wafer_count good_wafers yield_rate cycle_time_hours hold_hours",
        (
            "L1",
            "Logic-A",
            7,
            "logic",
            "normal",
            "2020-01-01",
            None,
            "active",
            25,
            24,
            0.96,
            10.0,
            0.0,
        ),
    ),
    "lot_process_history": records(
        "lot_id operation_seq layer_name process_step equipment_id chamber recipe run_time queue_hours rework_flag",
        ("L1", 1, "M1", "CMP", "CMP-01", "A", "R1", "2020-01-02", 1.0, 0),
    ),
    "lot_excursions": records(
        "lot_id operation_seq run_time process_step equipment_id excursion_code measurement_name measurement_value measurement_unit spec_lsl spec_usl",
        (
            "L1",
            1,
            "2020-01-02",
            "CMP",
            "CMP-01",
            "E001",
            "thickness",
            8.0,
            "nm",
            9.0,
            11.0,
        ),
    ),
    "lot_defects": records(
        "lot_id detected_time process_step defect_type count disposition",
        ("L1", "2020-01-03", "CMP", "Particle", 2, "review"),
    ),
    "lot_wafer_maps": records(
        "lot_id wafer_no detected_time process_step equipment_id pattern_class tested_dies failed_dies",
        ("L1", 1, "2020-01-04", "CMP", "CMP-01", "edge", 100, 2),
    ),
}
SQLITE_ROWS = {
    "product_yield": records(
        "product technology_nm lots wafers yield_pct", ("P1", 28, 2, 30, 93.33)
    ),
    "equipment_events": records(
        "equipment_id event_time event_type duration_minutes severity reason",
        ("CMP-01", "2026-01-02", "alarm", 2.0, "high", "r"),
    ),
    "equipment_excursions": records(
        "lot_id run_time process_step equipment_id excursion_code measurement_name measurement_value measurement_unit spec_lsl spec_usl",
        ("L2", "2026-01-02", "CMP", "CMP-01", "E2", "m", 2.0, "nm", 0.0, 3.0),
    ),
    "lot_identity": records(
        "lot_id product technology_nm route priority start_time complete_time status wafer_count good_wafers yield_rate cycle_time_hours hold_hours",
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
    ),
    "lot_process_history": records(
        "lot_id operation_seq layer_name process_step equipment_id chamber recipe run_time queue_hours rework_flag",
        ("L1", 1, "M1", "ETCH", "ETCH-01", "C", "r", "2020-01-01", 2.0, 1),
        ("L1", 2, "M2", "CMP", "CMP-01", "C", "r", "2020-01-02", 1.0, 0),
    ),
    "lot_excursions": records(
        "lot_id operation_seq run_time process_step equipment_id excursion_code measurement_name measurement_value measurement_unit spec_lsl spec_usl",
        ("L1", 1, "2020-01-01", "ETCH", "ETCH-01", "E1", "m", 1.0, "nm", 0.0, 2.0),
        ("L1", 2, "2020-01-02", "CMP", "CMP-01", "", "m", -1.0, "nm", None, 1.0),
    ),
    "lot_defects": records(
        "lot_id detected_time process_step defect_type count disposition",
        ("L1", "2020-01-01", "CMP", "D", 2, "hold"),
    ),
    "lot_wafer_maps": records(
        "lot_id wafer_no detected_time process_step equipment_id pattern_class tested_dies failed_dies",
        ("L1", 1, "2020-01-01", "CMP", "CMP-01", "edge", 10, 0),
        ("L1", 2, "2020-01-02", "CMP", "CMP-01", "ring", 10, 1),
    ),
}


class NamedQueriesRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = adapter_tests.NamedQueryAdapterTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def run_demo(
        self, adapter: str, mode: str, tool: str, arguments: dict, *extra: str
    ) -> dict:
        args = [
            "--adapter",
            adapter,
            "--mode",
            mode,
            "--tool",
            tool,
            "--arguments",
            json.dumps(arguments),
            "--as-of",
            "2026-01-02",
            "--manufacturing-db",
            str(self.fixture.manufacturing),
            "--equipment-db",
            str(self.fixture.equipment),
            "--quality-db",
            str(self.fixture.quality),
            *extra,
        ]
        return asyncio.run(demo._run(demo._parser().parse_args(args)))

    def test_all_32_paths_have_full_results_scope_and_single_budget(self) -> None:
        for adapter, expected in (("fake", FAKE_ROWS), ("sqlite", SQLITE_ROWS)):
            for mode in ("ready", "loop"):
                for tool, arguments, kind, grain in CASES:
                    with self.subTest(adapter=adapter, mode=mode, tool=tool):
                        payload = self.run_demo(adapter, mode, tool, arguments)
                        result = payload["typed_results"][0]
                        self.assertEqual(
                            (
                                result["tool"],
                                result["status"],
                                result["state"],
                                result["version"],
                                result["error"],
                            ),
                            (tool, "succeeded", "completed", "1.0.0", None),
                        )
                        self.assertEqual(result["data"], expected[kind])
                        self.assertEqual(result["row_count"], len(expected[kind]))
                        self.assertEqual(payload["adapter_kind"], adapter)
                        self.assertEqual(payload["guard"]["per_tool_calls"], {tool: 1})
                        self.assertEqual(payload["plan"]["budget"]["max_tool_calls"], 1)
                        observation = payload["observations"][0]
                        self.assertEqual(
                            (
                                observation["source_ref"],
                                observation["result"],
                                observation["arguments"],
                            ),
                            ("TOOL:S01", expected[kind], arguments),
                        )
                        scope = {
                            "tenant_id": "demo",
                            "start": arguments.get("start"),
                            "end": arguments.get("end"),
                            "equipment_ids": [arguments["equipment_id"]]
                            if "equipment_id" in arguments
                            else [],
                            "process_steps": [arguments["process_step"]]
                            if "process_step" in arguments
                            else [],
                            "lot_ids": [arguments["lot_id"]]
                            if "lot_id" in arguments
                            else [],
                            "grain": grain,
                        }
                        source = payload["sources"][f"{adapter}:named-query/{kind}"]
                        self.assertEqual(
                            (source["source_kind"], source["scope"]), (adapter, scope)
                        )
                        self.assertEqual(
                            payload["model_response_calls"], 0 if mode == "ready" else 2
                        )
                        self.assertEqual(
                            payload["model_tool_selection_calls"],
                            0 if mode == "ready" else 1,
                        )
                        if mode == "loop":
                            message = payload["tool_messages"][0]
                            self.assertEqual(message["tool_call_id"], "named-query-1")
                            self.assertEqual(
                                json.loads(message["content"])["data"], expected[kind]
                            )

    def test_empty_results_retain_consulted_source(self) -> None:
        for adapter in ("fake", "sqlite"):
            for mode in ("ready", "loop"):
                with (
                    self.subTest(adapter=adapter, mode=mode),
                    patch.object(demo, "_fixture", return_value=()),
                ):
                    payload = self.run_demo(
                        adapter, mode, "get_lot_identity", {"lot_id": "MISSING"}
                    )
                    result = payload["typed_results"][0]
                    self.assertEqual(
                        (result["status"], result["data"], result["row_count"]),
                        ("succeeded", [], 0),
                    )
                    self.assertEqual(len(payload["sources"]), 1)

    def test_invalid_and_unauthorized_calls_never_reach_sources(self) -> None:
        invalid = [
            ("get_product_yield_breakdown", {key: "x"}, ())
            for key in ("sql", "kind", "table", "order", "limit", "cursor")
        ]
        invalid += [
            ("get_product_yield_breakdown", {"start": value}, ())
            for value in ("bad", "20260101", None, True)
        ]
        invalid += [
            ("get_equipment_excursion_history", {"process_step": "unknown"}, ()),
            ("get_lot_identity", {}, ()),
            ("get_lot_identity", {"lot_id": None}, ()),
            ("get_lot_identity", {"lot_id": "L1", "start": "2020-01-01"}, ()),
        ]
        cases = [
            (tool, args, extra, "invalid_arguments", "validation")
            for tool, args, extra in invalid
        ]
        cases += [
            (
                "get_lot_identity",
                {"lot_id": "L1"},
                ("--role", "viewer"),
                "denied",
                "authorization",
            ),
            (
                "get_lot_identity",
                {"lot_id": "L1"},
                ("--tenant", "other"),
                "denied",
                "authorization",
            ),
            (
                "query_manufacturing_data",
                {"sql": "SELECT 1"},
                (),
                "denied",
                "authorization",
            ),
        ]
        for adapter in ("fake", "sqlite"):
            for mode in ("ready", "loop"):
                for tool, arguments, extra, status, kind in cases:
                    with (
                        self.subTest(
                            adapter=adapter,
                            mode=mode,
                            tool=tool,
                            arguments=arguments,
                            extra=extra,
                        ),
                        patch.object(
                            FakeNamedQueryAdapter,
                            "fetch",
                            side_effect=AssertionError("unexpected fake"),
                        ) as fake,
                        patch.object(
                            SQLiteNamedQueryAdapter,
                            "fetch",
                            side_effect=AssertionError("unexpected SQLite"),
                        ) as sql,
                        patch(
                            "app.tools.named_queries.data_source.sqlite3.connect",
                            side_effect=AssertionError("unexpected connection"),
                        ) as connect,
                    ):
                        payload = self.run_demo(adapter, mode, tool, arguments, *extra)
                        result = payload["typed_results"][0]
                        self.assertEqual(
                            (
                                result["status"],
                                result["error"]["kind"],
                                payload["adapter_kind"],
                            ),
                            (status, kind, adapter),
                        )
                        self.assertEqual(
                            (fake.call_count, sql.call_count, connect.call_count),
                            (0, 0, 0),
                        )

    def test_source_failures_and_timeout_do_not_fall_back(self) -> None:
        for mode in ("ready", "loop"):
            with (
                self.subTest(mode=mode, source="fake"),
                patch.object(
                    FakeNamedQueryAdapter,
                    "fetch",
                    side_effect=NamedQueryDataError("private path"),
                ) as fake,
                patch.object(
                    SQLiteNamedQueryAdapter,
                    "fetch",
                    side_effect=AssertionError("unexpected fallback"),
                ) as sql,
            ):
                payload = self.run_demo(
                    "fake", mode, "get_lot_identity", {"lot_id": "L1"}
                )
                self.assertEqual((fake.call_count, sql.call_count), (1, 0))
                self.assertEqual(
                    (
                        payload["typed_results"][0]["status"],
                        payload["typed_results"][0]["error"]["kind"],
                    ),
                    ("failed", "data_source"),
                )
            original = SQLiteNamedQueryAdapter.fetch
            with (
                self.subTest(mode=mode, source="sqlite"),
                patch.object(
                    SQLiteNamedQueryAdapter,
                    "fetch",
                    autospec=True,
                    side_effect=original,
                ) as sql,
                patch.object(
                    FakeNamedQueryAdapter,
                    "fetch",
                    side_effect=AssertionError("unexpected fallback"),
                ) as fake,
                patch(
                    "app.tools.named_queries.data_source.sqlite3.connect",
                    side_effect=sqlite3.OperationalError("private endpoint"),
                ) as connect,
            ):
                payload = self.run_demo(
                    "sqlite", mode, "get_lot_identity", {"lot_id": "L1"}
                )
                result = payload["typed_results"][0]
                self.assertEqual(
                    (sql.call_count, fake.call_count, connect.call_count), (1, 0, 1)
                )
                self.assertEqual(
                    (result["status"], result["error"]["kind"]),
                    ("failed", "data_source"),
                )
                self.assertNotIn("private", result["error"]["public_message"])
                self.assertEqual(payload["sources"], {})
            with (
                self.subTest(mode=mode, source="timeout"),
                patch.object(
                    FakeNamedQueryAdapter,
                    "fetch",
                    side_effect=NamedQueryTimeoutError("private timeout"),
                ) as fake,
            ):
                result = self.run_demo(
                    "fake", mode, "get_lot_identity", {"lot_id": "L1"}
                )["typed_results"][0]
                self.assertEqual(
                    (fake.call_count, result["status"], result["error"]["kind"]),
                    (1, "timed_out", "timeout"),
                )

    def test_loop_model_requires_matching_tool_message(self) -> None:
        model = demo._LoopModel("get_lot_identity", '{"lot_id":"L1"}')
        asyncio.run(model.complete(None, None))
        with self.assertRaisesRegex(AssertionError, "tool message"):
            asyncio.run(model.complete(ModelRequest("second", ()), None))
