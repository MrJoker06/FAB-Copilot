from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.agent_runtime.tools.contracts import ToolExecutionContext
from app.integrations.manufacturing.fake_equipment_health import (
    FakeEquipmentHealthAdapter,
)
from app.integrations.manufacturing.sqlite_equipment_health import (
    SQLiteEquipmentHealthAdapter,
)
from app.manufacturing import reports
from app.manufacturing.equipment_health.binding import (
    EQUIPMENT_HEALTH_DEFINITION,
    create_equipment_health_binding,
)
from app.manufacturing.equipment_health.contracts import (
    EquipmentHealthInput,
)

AS_OF = date(2026, 10, 24)


class FrozenDate(date):
    @classmethod
    def today(cls):
        return AS_OF


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "user"
    roles: tuple[str, ...] = ("analyst",)


class EquipmentHealthEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.main, self.equipment = root / "manufacturing.db", root / "equipment.db"
        with sqlite3.connect(self.main) as c:
            c.execute(
                "CREATE TABLE process_runs (equipment_id,process_step,run_time,excursion_code,defect_density,pass_flag)"
            )
            c.executemany(
                "INSERT INTO process_runs VALUES (?,?,?,?,?,?)",
                [
                    ("CMP-01", "CMP", "2026-10-01 00:00", None, 0.1, 1),
                    ("CMP-01", "CMP", "2026-10-24 23:59", "X", 0.2, 0),
                    ("CMP-02", "CMP", "2026-10-02", None, 0.3, 1),
                    ("ETCH-01", "ETCH", "2026-10-02", None, 0.4, 1),
                    ("BOUND-01", "CMP", "2026-07-26", None, 0.5, 1),
                    ("BOUND-01", "CMP", "2026-07-27", None, 0.6, 1),
                    ("NOEVENT-01", "CMP", "2026-10-02", None, 0.7, 1),
                    ("OLD-01", "CMP", "2026-09-30 23:59", None, 0.1, 1),
                    ("LATE-01", "CMP", "2026-10-25 00:00", None, 0.1, 1),
                ],
            )
        with sqlite3.connect(self.equipment) as c:
            c.execute(
                "CREATE TABLE equipment_events (equipment_id,event_time,duration_minutes)"
            )
            c.executemany(
                "INSERT INTO equipment_events VALUES (?,?,?)",
                [
                    ("CMP-01", "2026-10-03", 499.96),
                    ("CMP-02", "2026-10-03", 10.0),
                    ("ETCH-01", "2026-10-03", 10.0),
                ],
            )

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def legacy_session(self):
        connection = sqlite3.connect(self.main)
        connection.row_factory = sqlite3.Row
        connection.execute("ATTACH DATABASE ? AS equipment", (str(self.equipment),))
        # old SQL reads unqualified equipment_events, provide a temp view.
        connection.execute(
            "CREATE TEMP VIEW equipment_events AS SELECT * FROM equipment.equipment_events"
        )
        try:
            yield connection
        finally:
            connection.close()

    def new(self, arguments):
        binding = create_equipment_health_binding(
            SQLiteEquipmentHealthAdapter(
                self.main, self.equipment, demo_tenant_id="demo"
            ),
            today=lambda: AS_OF,
        )
        value = EquipmentHealthInput.from_arguments(arguments)
        return binding, binding.handler(
            value, ToolExecutionContext(Principal(), "r", "c", binding.dependencies)
        )

    def test_legacy_matrix_all_process_equipment_defaults_and_boundaries(self):
        cases = (
            (
                {},
                [
                    ("CMP-01", 2),
                    ("CMP-02", 1),
                    ("ETCH-01", 1),
                    ("BOUND-01", 1),
                    ("NOEVENT-01", 1),
                    ("OLD-01", 1),
                ],
            ),
            (
                {"start": "2026-07-26", "end": "2026-10-24"},
                [
                    ("CMP-01", 2),
                    ("CMP-02", 1),
                    ("ETCH-01", 1),
                    ("BOUND-01", 2),
                    ("NOEVENT-01", 1),
                    ("OLD-01", 1),
                ],
            ),
            (
                {"start": "2026-10-01"},
                [("CMP-01", 2), ("CMP-02", 1), ("ETCH-01", 1), ("NOEVENT-01", 1)],
            ),
            (
                {"end": "2026-10-23"},
                [
                    ("CMP-01", 1),
                    ("CMP-02", 1),
                    ("ETCH-01", 1),
                    ("BOUND-01", 1),
                    ("NOEVENT-01", 1),
                    ("OLD-01", 1),
                ],
            ),
            (
                {"end": "2026-10-24"},
                [
                    ("CMP-01", 2),
                    ("CMP-02", 1),
                    ("ETCH-01", 1),
                    ("BOUND-01", 1),
                    ("NOEVENT-01", 1),
                    ("OLD-01", 1),
                ],
            ),
            (
                {"start": "2026-10-01", "end": "2026-10-24", "process_step": "cmp"},
                [("CMP-01", 2), ("CMP-02", 1), ("NOEVENT-01", 1)],
            ),
            {
                "arguments": {
                    "start": "2026-10-01",
                    "end": "2026-10-24",
                    "equipment_id": "cmp-01",
                    "process_step": "etch",
                },
                "expected": [("CMP-01", 2)],
            },
            {
                "arguments": {"start": "2026-10-24", "end": "2026-10-24"},
                "expected": [("CMP-01", 1)],
            },
            {
                "arguments": {"equipment_id": "unknown-01"},
                "expected": [],
            },
        )
        for case in cases:
            arguments, expected = (
                (case["arguments"], case["expected"])
                if isinstance(case, dict)
                else case
            )
            with self.subTest(arguments=arguments):
                _, result = self.new(arguments)
                with (
                    patch.object(reports, "db_session", self.legacy_session),
                    patch.object(reports, "date", FrozenDate),
                ):
                    old = reports.equipment_health(
                        arguments.get("start"),
                        arguments.get("end"),
                        arguments.get("process_step"),
                        arguments.get("equipment_id"),
                    )
                self.assertEqual(result.data, old)
                self.assertEqual(
                    json.dumps(result.data, sort_keys=True),
                    json.dumps(old, sort_keys=True),
                )
                self.assertEqual(
                    [(row["equipment_id"], row["runs"]) for row in result.data],
                    expected,
                )

                if arguments == {}:
                    no_event = next(
                        row
                        for row in result.data
                        if row["equipment_id"] == "NOEVENT-01"
                    )
                    self.assertEqual(
                        (no_event["events"], no_event["downtime_minutes"]), (0, 0)
                    )
                    self.assertEqual(
                        [row["equipment_id"] for row in result.data[:3]],
                        ["CMP-01", "CMP-02", "ETCH-01"],
                    )

    def test_fake_and_sqlite_bindings_have_same_definition_handler_data_different_source(
        self,
    ):
        arguments = {"start": "2026-10-01", "end": "2026-10-24", "process_step": "CMP"}
        sqlite_binding, sqlite_result = self.new(arguments)
        query = EquipmentHealthInput.from_arguments(arguments).resolve(AS_OF)
        snap = sqlite_binding.dependencies.port.fetch(query, Principal())
        fake_binding = create_equipment_health_binding(
            FakeEquipmentHealthAdapter("demo", {query: snap.rows}), today=lambda: AS_OF
        )
        fake_result = fake_binding.handler(
            EquipmentHealthInput.from_arguments(arguments),
            ToolExecutionContext(Principal(), "r", "c", fake_binding.dependencies),
        )
        self.assertIs(sqlite_binding.definition, EQUIPMENT_HEALTH_DEFINITION)
        self.assertIs(fake_binding.handler, sqlite_binding.handler)
        self.assertEqual(fake_result.data, sqlite_result.data)
        self.assertNotEqual(
            fake_result.sources[0].source_kind, sqlite_result.sources[0].source_kind
        )
