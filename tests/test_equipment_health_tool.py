from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolScope,
    ToolSource,
    ToolSourceKind,
)
from app.agent_runtime.tools.definition import ToolDefinition
from app.integrations.manufacturing.fake_equipment_health import (
    FakeEquipmentHealthAdapter,
)
from app.integrations.manufacturing.sqlite_equipment_health import (
    SQLiteEquipmentHealthAdapter,
)
from app.manufacturing.equipment_health.binding import (
    EQUIPMENT_HEALTH_DEFINITION,
    create_equipment_health_binding,
)
from app.manufacturing.equipment_health.contracts import (
    EquipmentHealthAggregate,
    EquipmentHealthDataError,
    EquipmentHealthInput,
    EquipmentHealthInputError,
    EquipmentHealthQuery,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "u"
    roles: tuple[str, ...] = ("analyst",)


AS_OF = date(2026, 10, 24)


def query(**changes):
    return EquipmentHealthQuery(AS_OF - timedelta(days=89), AS_OF, **changes)


def aggregate(equipment_id="CMP-01", excursions=3, downtime=200.0):
    return EquipmentHealthAggregate(
        equipment_id, 10, excursions, 0.125, 98.5, 2, downtime
    )


class EquipmentHealthToolTests(unittest.TestCase):
    def binding(self, port, today=lambda: AS_OF):
        return create_equipment_health_binding(port, today=today)

    def call(self, binding, arguments=None):
        value = binding.definition.parse(arguments or {})
        return binding.handler(
            value, ToolExecutionContext(Principal(), "r", "c", binding.dependencies)
        )

    def test_schema_exactly_matches_legacy_catalog_entry(self):
        from app.agent_runtime.tools.catalog import TOOLS

        legacy = next(
            item["function"]
            for item in TOOLS
            if item["function"]["name"] == "get_equipment_health"
        )
        self.assertEqual(EQUIPMENT_HEALTH_DEFINITION.description, legacy["description"])
        self.assertEqual(
            EQUIPMENT_HEALTH_DEFINITION.json_schema(), legacy["parameters"]
        )

    def test_schema_is_fresh_copy(self):
        first = EQUIPMENT_HEALTH_DEFINITION.json_schema()
        first["properties"]["start"]["type"] = "integer"
        self.assertEqual(
            EQUIPMENT_HEALTH_DEFINITION.json_schema()["properties"]["start"]["type"],
            "string",
        )

    def test_definition_delegates_schema_and_parse_to_one_input_authority(self):
        self.assertIsInstance(EQUIPMENT_HEALTH_DEFINITION, ToolDefinition)
        self.assertEqual(EQUIPMENT_HEALTH_DEFINITION.parse({}), EquipmentHealthInput())

    def test_defaults_independently_apply_to_partial_dates_and_730_is_allowed(self):
        self.assertEqual(
            EquipmentHealthInput(start="2026-10-02").resolve(AS_OF).end, AS_OF
        )
        self.assertEqual(
            EquipmentHealthInput(end="2026-10-23").resolve(AS_OF).start,
            date(2026, 7, 27),
        )
        self.assertEqual(
            EquipmentHealthInput(start="2024-10-24", end="2026-10-24")
            .resolve(AS_OF)
            .start,
            date(2024, 10, 24),
        )

    def test_input_rejects_unknown_sql_tenant_types_bad_dates_and_blank_id(self):
        for arguments in (
            {"sql": "select 1"},
            {"tenant_id": "x"},
            {"start": 1},
            {"start": "bad"},
            {"equipment_id": " "},
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(EquipmentHealthInputError),
            ):
                value = EquipmentHealthInput.from_arguments(arguments)
                value.resolve(AS_OF)

    def test_known_process_normalizes_and_invalid_process_fails_before_port(self):
        value = EquipmentHealthInput.from_arguments({"process_step": "cmp"})
        self.assertEqual(value.resolve(AS_OF).process_step, "CMP")
        port = FakeEquipmentHealthAdapter("demo", {})
        with self.assertRaises(EquipmentHealthInputError):
            self.call(self.binding(port), {"process_step": "unknown"})
        self.assertEqual(port.calls, [])

    def test_invalid_ranges_and_trusted_fields_never_reach_port(self):
        port = FakeEquipmentHealthAdapter("demo", {})
        binding = self.binding(port)
        for arguments in (
            {"start": "2026-10-25", "end": "2026-10-24"},
            {"start": "2024-10-23", "end": "2026-10-24"},
            {"start": "9999-12-30", "end": "9999-12-31"},
            {"query": "SELECT * FROM process_runs"},
            {"tenant_id": "other"},
            {"url": "https://not-a-source.invalid"},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(EquipmentHealthInputError):
                    self.call(binding, arguments)
                self.assertEqual(port.calls, [])

    def test_equipment_takes_precedence_over_process(self):
        requested = query(equipment_id="CMP-01")
        port = FakeEquipmentHealthAdapter("demo", {requested: (aggregate(),)})
        result = self.call(
            self.binding(port), {"process_step": "etch", "equipment_id": "cmp-01"}
        )
        self.assertEqual(port.calls, [requested])
        self.assertEqual(result.sources[0].scope.process_steps, ())

    def test_fake_wrong_tenant_has_no_read_and_unknown_query_never_reuses_fixture(self):
        port = FakeEquipmentHealthAdapter("other", {query(): (aggregate(),)})
        with self.assertRaises(EquipmentHealthDataError):
            self.call(self.binding(port))
        self.assertEqual(port.calls, [])
        port = FakeEquipmentHealthAdapter("demo", {query(): (aggregate(),)})
        with self.assertRaises(EquipmentHealthDataError):
            self.call(self.binding(port), {"start": "2026-10-02"})
        self.assertEqual(len(port.calls), 1)

    def test_health_boundaries_and_order(self):
        requested = query()
        rows = (
            aggregate("A", 2, 199.9),
            aggregate("B", 3, 1),
            aggregate("C", 1, 500.0),
            aggregate("D", 8, 1),
        )
        result = self.call(
            self.binding(FakeEquipmentHealthAdapter("demo", {requested: rows}))
        )
        self.assertEqual(
            [row["health"] for row in result.data],
            ["Critical", "Critical", "Watch", "Healthy"],
        )
        self.assertEqual([row["equipment_id"] for row in result.data[:2]], ["D", "C"])

    def test_scope_inconsistent_and_bad_data_fail_without_fabrication(self):
        class BadPort:
            def fetch(self, requested, principal):
                return type(
                    "Snapshot",
                    (),
                    {
                        "query": requested,
                        "rows": (aggregate("OTHER"),),
                        "source": ToolSource(
                            "x",
                            "x",
                            ToolSourceKind.FAKE,
                            ToolScope("other", requested.start, requested.end),
                        ),
                    },
                )()

        with self.assertRaises(EquipmentHealthDataError):
            self.call(self.binding(BadPort()))
        with self.assertRaises(EquipmentHealthDataError):
            EquipmentHealthAggregate("X", -1, 0, 0.0, 0.0, 0, 0.0)

    def test_direct_constructor_and_null_json_are_strict(self):
        with self.assertRaises(EquipmentHealthInputError):
            EquipmentHealthInput(start=3)  # type: ignore[arg-type]
        with self.assertRaises(EquipmentHealthInputError):
            EquipmentHealthInput.from_arguments({"start": None})
        with self.assertRaises(EquipmentHealthInputError):
            EquipmentHealthInput(end="9999-12-31").resolve(AS_OF)
        with self.assertRaises(EquipmentHealthInputError):
            EquipmentHealthQuery(AS_OF, AS_OF, "CMP", "CMP-01")
        with self.assertRaises(EquipmentHealthDataError):
            EquipmentHealthAggregate("X", 1, 2, 0.0, 101.0, 0, 0.0)

    def test_source_scope_must_exactly_match_effective_query(self):
        class BadPort:
            def fetch(self, value, principal):
                return type(
                    "Snapshot",
                    (),
                    {
                        "query": value,
                        "rows": (aggregate(),),
                        "source": ToolSource(
                            "x",
                            "x",
                            ToolSourceKind.FAKE,
                            ToolScope(
                                principal.tenant_id,
                                value.start,
                                value.end,
                                process_steps=("CMP",),
                                grain="equipment",
                            ),
                        ),
                    },
                )()

        with self.assertRaises(EquipmentHealthDataError):
            self.call(self.binding(BadPort()), {"equipment_id": "CMP-01"})

    def test_demo_cli_fake_and_invalid_request_have_controlled_results(self):
        command = [
            sys.executable,
            "scripts/demo_equipment_health.py",
            "--as-of",
            AS_OF.isoformat(),
        ]
        ok = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(ok.returncode, 0)
        self.assertEqual(json.loads(ok.stdout)["status"], "succeeded")
        bad = subprocess.run(
            [*command, "--arguments", '{"sql":"x"}'],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout)["status"], "invalid_arguments")

    def test_demo_cli_unexpected_failure_is_sanitized(self):
        from scripts import demo_equipment_health

        stdout, stderr = StringIO(), StringIO()
        with (
            patch.object(
                demo_equipment_health,
                "create_equipment_health_binding",
                side_effect=RuntimeError("secret path"),
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = demo_equipment_health.main(["--as-of", AS_OF.isoformat()])

        self.assertEqual(exit_code, 2)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"status": "failed", "error": {"code": "INTERNAL_ERROR"}},
        )
        self.assertNotIn("secret path", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("traceback", (stdout.getvalue() + stderr.getvalue()).lower())

    def _databases(self, root: Path):
        manufacturing, equipment = root / "m.db", root / "e.db"
        with sqlite3.connect(manufacturing) as conn:
            conn.execute(
                "CREATE TABLE process_runs (equipment_id, process_step, run_time, excursion_code, defect_density, pass_flag)"
            )
            conn.executemany(
                "INSERT INTO process_runs VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("CMP-01", "CMP", "2026-10-02", None, 0.1234, 1),
                    ("CMP-01", "CMP", "2026-10-03", "E", 0.1266, 0),
                    ("ETCH-02", "ETCH", "2026-10-03", None, 0.3, 1),
                ],
            )
        with sqlite3.connect(equipment) as conn:
            conn.execute(
                "CREATE TABLE equipment_events (equipment_id, event_time, duration_minutes)"
            )
            conn.executemany(
                "INSERT INTO equipment_events VALUES (?, ?, ?)",
                [("CMP-01", "2026-10-02", 499.96), ("CMP-01", "2026-10-03", 0.0)],
            )
        return manufacturing, equipment

    def test_sqlite_is_readonly_equivalent_filters_rounding_and_source(self):
        with tempfile.TemporaryDirectory() as temp:
            m, e = self._databases(Path(temp))
            port = SQLiteEquipmentHealthAdapter(m, e, demo_tenant_id="demo")
            result = self.call(
                self.binding(port),
                {"start": "2026-10-01", "end": "2026-10-24", "equipment_id": "cmp-01"},
            )
            self.assertEqual(result.data[0]["health"], "Critical")
            self.assertEqual(result.data[0]["avg_defect_density"], 0.125)
            self.assertEqual(result.data[0]["downtime_minutes"], 500.0)
            self.assertEqual(result.sources[0].source_kind, ToolSourceKind.SQLITE)
            with self.assertRaises(sqlite3.OperationalError):
                sqlite3.connect(f"file:{m}?mode=ro", uri=True).execute(
                    "INSERT INTO process_runs VALUES (1,1,1,1,1,1)"
                )

    def test_sqlite_wrong_tenant_does_not_connect_or_create_missing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.db"
            port = SQLiteEquipmentHealthAdapter(
                missing, missing, demo_tenant_id="other"
            )
            with (
                patch("sqlite3.connect") as connect,
                self.assertRaises(EquipmentHealthDataError),
            ):
                self.call(self.binding(port))
            connect.assert_not_called()
            self.assertFalse(missing.exists())

    def test_sqlite_source_failure_never_falls_back_fake(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.db"
            with self.assertRaises(EquipmentHealthDataError):
                self.call(
                    self.binding(
                        SQLiteEquipmentHealthAdapter(
                            missing, missing, demo_tenant_id="demo"
                        )
                    )
                )
            self.assertFalse(missing.exists())

    def test_sql_injection_is_literal_not_a_broadened_query(self):
        with tempfile.TemporaryDirectory() as temp:
            m, e = self._databases(Path(temp))
            port = SQLiteEquipmentHealthAdapter(m, e, demo_tenant_id="demo")
            result = self.call(
                self.binding(port),
                {
                    "start": "2026-10-01",
                    "end": "2026-10-24",
                    "equipment_id": "CMP-01' OR 1=1 --",
                },
            )
            self.assertEqual(result.data, [])

    def test_cli_sqlite_requires_explicit_paths(self):
        result = subprocess.run(
            [sys.executable, "scripts/demo_equipment_health.py", "--adapter", "sqlite"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_new_sqlite_matches_legacy_reports_for_equipment_scope(self):
        from app.manufacturing import reports

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manufacturing, equipment = self._databases(root)
            # The legacy report uses one attached application connection; this
            # disposable fixture deliberately exposes the same two tables.
            legacy = root / "legacy.db"
            with sqlite3.connect(legacy) as connection:
                connection.execute(
                    "CREATE TABLE process_runs (equipment_id, process_step, run_time, excursion_code, defect_density, pass_flag)"
                )
                connection.execute(
                    "CREATE TABLE equipment_events (equipment_id, event_time, duration_minutes)"
                )
                with sqlite3.connect(manufacturing) as source:
                    connection.executemany(
                        "INSERT INTO process_runs VALUES (?,?,?,?,?,?)",
                        source.execute("SELECT * FROM process_runs"),
                    )
                with sqlite3.connect(equipment) as source:
                    connection.executemany(
                        "INSERT INTO equipment_events VALUES (?,?,?)",
                        source.execute("SELECT * FROM equipment_events"),
                    )

            @contextmanager
            def session():
                connection = sqlite3.connect(legacy)
                connection.row_factory = sqlite3.Row
                try:
                    yield connection
                finally:
                    connection.close()

            port = SQLiteEquipmentHealthAdapter(
                manufacturing, equipment, demo_tenant_id="demo"
            )
            new = self.call(
                self.binding(port),
                {"start": "2026-10-01", "end": "2026-10-24", "equipment_id": "CMP-01"},
            ).data
            with patch.object(reports, "db_session", session):
                old = reports.equipment_health(
                    "2026-10-01", "2026-10-24", equipment_id="CMP-01"
                )
            self.assertEqual(new, old)
