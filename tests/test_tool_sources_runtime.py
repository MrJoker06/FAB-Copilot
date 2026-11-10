"""Runtime contract coverage for the explicit MOD-009 source composition."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.bootstrap.enterprise_tools_demo import ProviderEnterpriseToolsAdapter
from app.bootstrap.knowledge_search_demo import BackendKnowledgeSearchAdapter
from app.bootstrap.tool_sources import ToolSources, create_tool_bindings
from app.bootstrap.tool_sources_demo import (
    build_fake_sources,
    build_local_sources,
    run_tool_sources,
)
from app.demo_data.tool_sources.equipment_health import (
    FakeEquipmentHealthAdapter,
)
from app.tools.equipment_health.data_source import (
    SQLiteEquipmentHealthAdapter,
)
from app.tools.equipment_health.contracts import (
    EquipmentHealthAggregate,
    EquipmentHealthDataError,
    EquipmentHealthQuery,
)

AS_OF = date(2026, 10, 24)
LOT_TOOLS = frozenset(
    {
        "get_lot_identity",
        "get_lot_process_history",
        "get_lot_excursion_history",
        "get_lot_defect_history",
        "get_lot_wafer_map_patterns",
    }
)
SQLITE_DATES = {"start": "2026-01-01", "end": "2026-01-31"}
SQLITE_EXPECTATIONS = {
    "get_equipment_health": (
        "equipment",
        {"runs": 1, "excursions": 1, "downtime_minutes": 5.0},
    ),
    "get_process_capability": (
        "equipment_distribution",
        {"samples": 1, "mean_value": 1.0, "metric_name": "thickness"},
    ),
    "get_sensor_summary": (
        "equipment_signal",
        {"samples": 1, "signal_name": "pressure", "mean_value": 1.0},
    ),
    "get_fab_overview": (
        "fab_overview",
        {"lots": 1, "wafers": 10, "yield_pct": 90.0, "avg_cycle_hours": 8.0},
    ),
    "get_yield_trend": (
        "weekly_yield",
        {"lots": 1, "yield_pct": 90.0, "cycle_hours": 8.0},
    ),
    "get_process_pass_rate": (
        "process_pass_rate",
        {"runs": 1, "passed_runs": 1, "pass_pct": 100.0},
    ),
    "get_equipment_productivity": (
        "equipment_productivity",
        {"productive_minutes": 60.0, "productive_pct": 100.0},
    ),
    "get_defect_pareto": (
        "defect_type",
        {"defect_type": "Particle", "defect_count": 2, "share_pct": 100.0},
    ),
    "get_recent_excursions": ("process_run", {"lot_id": "L1", "excursion_code": "E1"}),
    "get_product_yield_breakdown": (
        "product",
        {"product": "P1", "lots": 1, "wafers": 10, "yield_pct": 90.0},
    ),
    "get_equipment_event_timeline": (
        "event",
        {"event_type": "alarm", "duration_minutes": 5.0},
    ),
    "get_equipment_excursion_history": (
        "event",
        {"lot_id": "L1", "excursion_code": "E1"},
    ),
    "get_lot_identity": ("lot", {"wafer_count": 10, "yield_rate": 0.9}),
    "get_lot_process_history": ("process_run", {"operation_seq": 1, "chamber": "C"}),
    "get_lot_excursion_history": (
        "event",
        {"operation_seq": 1, "excursion_code": "E1"},
    ),
    "get_lot_defect_history": ("defect_event", {"defect_type": "Particle", "count": 2}),
    "get_lot_wafer_map_patterns": ("wafer", {"tested_dies": 10, "failed_dies": 1}),
}


@dataclass(frozen=True, slots=True)
class _Principal:
    tenant_id: str = "demo"
    user_id: str = "tool-sources-runtime"
    roles: tuple[str, ...] = ("analyst",)


def _arguments(tool: str, *, sqlite_profile: bool = False) -> dict[str, object]:
    values: dict[str, object] = {}
    if sqlite_profile and tool not in {
        "get_enterprise_data_manifest",
        "get_enterprise_fab_summary",
        "query_enterprise_data",
        "search_knowledge",
    }:
        values.update(SQLITE_DATES)
    if tool in LOT_TOOLS:
        values = {"lot_id": "L1" if sqlite_profile else "LOT-001"}
    elif tool == "search_knowledge":
        values = {"query": "LITHO 颗粒"}
    elif tool == "get_process_pass_rate":
        values.update({"process_step": "CMP", "equipment_id": "CMP-01"})
    elif tool == "query_enterprise_data":
        values = {"entity": "lots"}
    return values


def _run(sources: ToolSources, tool: str, mode: str, **kwargs: Any) -> dict[str, Any]:
    return asyncio.run(
        run_tool_sources(sources, tool=tool, mode=mode, as_of=AS_OF, **kwargs)
    )


@contextmanager
def _sqlite_fixture_connection(path: Path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _create_local_fixture(root: Path) -> tuple[Path, Path, Path]:
    """Small union schema supporting the 17 SQLite-backed contracts."""
    manufacturing, equipment, quality = (
        root / "manufacturing.db",
        root / "equipment.db",
        root / "quality.db",
    )
    with _sqlite_fixture_connection(manufacturing) as connection:
        connection.execute(
            """CREATE TABLE lots (lot_id TEXT, product TEXT, technology_nm INTEGER, route TEXT, priority TEXT, start_time TEXT, complete_time TEXT, status TEXT, wafer_count INTEGER, good_wafers INTEGER, yield_rate REAL, cycle_time_hours REAL, hold_hours REAL)"""
        )
        connection.execute(
            """CREATE TABLE process_runs (run_time TEXT, lot_id TEXT, operation_seq INTEGER, layer_name TEXT, process_step TEXT, equipment_id TEXT, chamber TEXT, recipe TEXT, queue_hours REAL, rework_flag INTEGER, excursion_code TEXT, thickness_nm REAL, uniformity_pct REAL, defect_density REAL, measurement_name TEXT, measurement_value REAL, measurement_unit TEXT, spec_lsl REAL, spec_usl REAL, pass_flag INTEGER)"""
        )
        connection.execute(
            "INSERT INTO lots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "L1",
                "P1",
                28,
                "R",
                "Normal",
                "2026-01-01",
                "2026-01-02",
                "Completed",
                10,
                9,
                0.9,
                8.0,
                1.0,
            ),
        )
        connection.execute(
            "INSERT INTO process_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-01-02",
                "L1",
                1,
                "M1",
                "CMP",
                "CMP-01",
                "C",
                "recipe",
                1.0,
                0,
                "E1",
                1.0,
                0.1,
                0.2,
                "thickness",
                1.0,
                "nm",
                0.5,
                1.5,
                1,
            ),
        )
    with _sqlite_fixture_connection(equipment) as connection:
        connection.execute(
            "CREATE TABLE equipment_events (equipment_id TEXT, event_time TEXT, event_type TEXT, duration_minutes REAL, severity TEXT, reason TEXT)"
        )
        connection.execute(
            "CREATE TABLE sensor_readings (sample_time TEXT, process_step TEXT, equipment_id TEXT, signal_name TEXT, signal_unit TEXT, is_missing INTEGER, is_outlier INTEGER, signal_value REAL)"
        )
        connection.execute(
            "CREATE TABLE equipment_state_intervals (equipment_id TEXT, start_time TEXT, duration_minutes REAL, semi_e10_state TEXT)"
        )
        connection.execute(
            "INSERT INTO equipment_events VALUES ('CMP-01', '2026-01-02', 'alarm', 5, 'high', 'fixture')"
        )
        connection.execute(
            "INSERT INTO sensor_readings VALUES ('2026-01-02', 'CMP', 'CMP-01', 'pressure', 'kPa', 0, 0, 1.0)"
        )
        connection.execute(
            "INSERT INTO equipment_state_intervals VALUES ('CMP-01', '2026-01-02', 60, 'Productive')"
        )
    with _sqlite_fixture_connection(quality) as connection:
        connection.execute(
            "CREATE TABLE defect_records (lot_id TEXT, detected_time TEXT, process_step TEXT, defect_type TEXT, count INTEGER, disposition TEXT)"
        )
        connection.execute(
            "CREATE TABLE wafer_maps (lot_id TEXT, wafer_no INTEGER, detected_time TEXT, process_step TEXT, equipment_id TEXT, pattern_class TEXT, tested_dies INTEGER, failed_dies INTEGER)"
        )
        connection.execute(
            "INSERT INTO defect_records VALUES ('L1', '2026-01-02', 'CMP', 'Particle', 2, 'hold')"
        )
        connection.execute(
            "INSERT INTO wafer_maps VALUES ('L1', 1, '2026-01-02', 'CMP', 'CMP-01', 'edge', 10, 1)"
        )
    return manufacturing, equipment, quality


class _SpyEquipmentPort:
    def __init__(self, delegate: Any, *, fail: bool = False) -> None:
        self.delegate, self.fail, self.calls = delegate, fail, 0

    def fetch(self, query: EquipmentHealthQuery, principal: _Principal):
        self.calls += 1
        if self.fail:
            raise EquipmentHealthDataError("private marker/path")
        return self.delegate.fetch(query, principal)


def _assert_seeded_sqlite_result(
    case: unittest.TestCase, tool: str, outcome: dict[str, Any]
) -> None:
    grain, expected = SQLITE_EXPECTATIONS[tool]
    data = outcome["data"]
    row = data[0] if isinstance(data, list) else data
    case.assertIsInstance(row, dict)
    for key, value in expected.items():
        case.assertEqual(row[key], value)
    scope = outcome["sources"][0]["scope"]
    case.assertEqual(scope["grain"], grain)
    if tool in LOT_TOOLS:
        case.assertIsNone(scope["start"])
        case.assertIsNone(scope["end"])
        case.assertEqual(scope["lot_ids"], ["L1"])
    else:
        case.assertEqual(scope["start"], "2026-01-01")
        case.assertEqual(scope["end"], "2026-01-31")
        case.assertEqual(scope["lot_ids"], [])


class ToolSourceRuntimeTests(unittest.TestCase):
    def test_every_canonical_fake_binding_runs_ready_and_loop_with_lineage(
        self,
    ) -> None:
        sources = build_fake_sources(AS_OF)
        bindings = create_tool_bindings(sources, as_of=AS_OF, default_tenant_id="demo")
        names = tuple(binding.definition.name for binding in bindings)
        self.assertEqual(len(names), 21)
        self.assertEqual(len(set(names)), 21)
        self.assertEqual(
            len(
                create_tool_bindings(
                    sources,
                    as_of=AS_OF,
                    default_tenant_id="demo",
                    include_equipment_health_summary=True,
                )
            ),
            22,
        )
        for tool in names:
            for mode in ("ready", "loop"):
                with self.subTest(tool=tool, mode=mode):
                    outcome = _run(sources, tool, mode, arguments=_arguments(tool))
                    self.assertEqual(outcome["status"], "succeeded")
                    self.assertEqual(outcome["guard_total_calls"], 1)
                    self.assertEqual(
                        outcome["model_calls"], 0 if mode == "ready" else 2
                    )
                    self.assertTrue(outcome["data"])
                    self.assertGreaterEqual(outcome["row_count"], 1)
                    self.assertTrue(outcome["sources"])
                    self.assertEqual(
                        {row["kind"] for row in outcome["sources"]}, {"fake"}
                    )
                    self.assertTrue(
                        all(
                            row["scope"]["tenant_id"] == "demo"
                            for row in outcome["sources"]
                        )
                    )

    def test_alternate_profile_preserves_bindings_and_uses_17_sqlite_3_provider_1_backend(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = _create_local_fixture(Path(directory))
            local, fake = (
                build_local_sources(*paths, as_of=AS_OF),
                build_fake_sources(AS_OF),
            )
            self.assertIsInstance(local.equipment_health, SQLiteEquipmentHealthAdapter)
            self.assertIsInstance(local.enterprise_data, ProviderEnterpriseToolsAdapter)
            self.assertIsInstance(local.knowledge_search, BackendKnowledgeSearchAdapter)
            fake_bindings = create_tool_bindings(
                fake, as_of=AS_OF, default_tenant_id="demo"
            )
            local_bindings = create_tool_bindings(
                local, as_of=AS_OF, default_tenant_id="demo"
            )
            self.assertEqual(
                [
                    (item.definition.name, item.definition.json_schema())
                    for item in fake_bindings
                ],
                [
                    (item.definition.name, item.definition.json_schema())
                    for item in local_bindings
                ],
            )
            self.assertTrue(
                all(
                    fake_item.definition is local_item.definition
                    and fake_item.handler is local_item.handler
                    for fake_item, local_item in zip(fake_bindings, local_bindings)
                )
            )
            for tool in (item.definition.name for item in local_bindings):
                arguments = _arguments(tool, sqlite_profile=True)
                for mode in ("ready", "loop"):
                    with self.subTest(tool=tool, mode=mode):
                        outcome = _run(local, tool, mode, arguments=arguments)
                        self.assertEqual(outcome["status"], "succeeded")
                        self.assertEqual(outcome["guard_total_calls"], 1)
                        self.assertEqual(
                            outcome["model_calls"], 0 if mode == "ready" else 2
                        )
                        self.assertTrue(outcome["data"])
                        expected_kind = (
                            "fake"
                            if tool.startswith(("get_enterprise", "query_enterprise"))
                            or tool == "search_knowledge"
                            else "sqlite"
                        )
                        self.assertEqual(
                            {row["kind"] for row in outcome["sources"]}, {expected_kind}
                        )
                        self.assertTrue(
                            all(
                                row["scope"]["tenant_id"] == "demo"
                                for row in outcome["sources"]
                            )
                        )
                        if tool in SQLITE_EXPECTATIONS:
                            _assert_seeded_sqlite_result(self, tool, outcome)
            for tool in (
                "get_enterprise_data_manifest",
                "get_enterprise_fab_summary",
                "query_enterprise_data",
            ):
                arguments = _arguments(tool, sqlite_profile=True)
                local_outcome = _run(local, tool, "ready", arguments=arguments)
                fake_outcome = _run(fake, tool, "ready", arguments=arguments)
                self.assertEqual(local_outcome["data"], fake_outcome["data"])
                self.assertEqual(
                    local_outcome["sources"][0]["scope"],
                    fake_outcome["sources"][0]["scope"],
                )
            local_knowledge = _run(
                local,
                "search_knowledge",
                "ready",
                arguments=_arguments("search_knowledge", sqlite_profile=True),
            )
            fake_knowledge = _run(
                fake,
                "search_knowledge",
                "ready",
                arguments=_arguments("search_knowledge", sqlite_profile=True),
            )
            self.assertEqual(
                [row["reference_id"] for row in local_knowledge["data"]],
                [row["reference_id"] for row in fake_knowledge["data"]],
            )

    def test_spy_port_proves_no_implicit_reads_and_safe_source_failure(self) -> None:
        query = EquipmentHealthQuery(date(2026, 7, 27), AS_OF)
        fixture = FakeEquipmentHealthAdapter(
            "demo",
            {
                query: (
                    EquipmentHealthAggregate("CMP-01", 10, 8, 0.1, 99.0, 1, 1.0),
                    EquipmentHealthAggregate("CMP-02", 10, 3, 0.1, 99.0, 1, 1.0),
                    EquipmentHealthAggregate("CMP-03", 10, 0, 0.1, 99.0, 1, 1.0),
                )
            },
        )
        spy, sources = _SpyEquipmentPort(fixture), None
        sources = ToolSources(equipment_health=spy)
        for tool, summary in (
            ("get_equipment_health", False),
            ("get_equipment_health_summary", True),
        ):
            for mode in ("ready", "loop"):
                with self.subTest(tool=tool, mode=mode):
                    spy.calls = 0
                    outcome = _run(sources, tool, mode, include_summary=summary)
                    self.assertEqual(spy.calls, 1)
                    self.assertEqual(outcome["guard_total_calls"], 1)
                    self.assertEqual(
                        outcome["model_calls"], 0 if mode == "ready" else 2
                    )
                    if summary:
                        self.assertEqual(outcome["model_tool_count"], 2)
                        self.assertEqual(
                            outcome["data"],
                            {
                                "equipment_count": 3,
                                "critical": 1,
                                "watch": 1,
                                "healthy": 1,
                            },
                        )
        for mode in ("ready", "loop"):
            for arguments, principal, budget in (
                ({"sql": "SELECT private"}, _Principal(), 1),
                ({}, _Principal(roles=("viewer",)), 1),
                ({}, _Principal(tenant_id="other"), 1),
                ({}, _Principal(), 0),
            ):
                with self.subTest(
                    mode=mode, arguments=arguments, principal=principal, budget=budget
                ):
                    spy.calls = 0
                    outcome = _run(
                        sources,
                        "get_equipment_health",
                        mode,
                        arguments=arguments,
                        principal=principal,
                        max_tool_calls=budget,
                    )
                    self.assertNotEqual(outcome["status"], "succeeded")
                    self.assertEqual(spy.calls, 0)
                    self.assertEqual(outcome["guard_total_calls"], 0)
            for rejected_tool in ("query_manufacturing_data", "unknown_sql_tool"):
                with self.subTest(mode=mode, rejected_tool=rejected_tool):
                    spy.calls = 0
                    outcome = _run(sources, rejected_tool, mode, arguments={})
                    self.assertNotEqual(outcome["status"], "succeeded")
                    self.assertEqual(spy.calls, 0)
                    self.assertEqual(outcome["guard_total_calls"], 0)
        failing = _SpyEquipmentPort(fixture, fail=True)
        for mode in ("ready", "loop"):
            with self.subTest(mode=mode, failure=True):
                failing.calls = 0
                outcome = _run(
                    ToolSources(equipment_health=failing), "get_equipment_health", mode
                )
                self.assertEqual(failing.calls, 1)
                self.assertEqual(outcome["status"], "failed")
                self.assertNotIn("private marker/path", str(outcome["error"]))


if __name__ == "__main__":
    unittest.main()
