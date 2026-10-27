from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from datetime import date

from app.agent_runtime.execution.tool_result_bridge import project_tool_result
from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolScope,
    ToolSource,
    ToolSourceKind,
    ToolStatus,
)
from app.agent_runtime.tools.dispatch_contracts import BudgetDecision, PolicyDecision
from app.agent_runtime.tools.dispatcher import ToolDispatcher
from app.agent_runtime.tools.tool_registry import ToolRegistry
from app.manufacturing.process_diagnostics.binding import (
    PROCESS_CAPABILITY_DEFINITION,
    SENSOR_SUMMARY_DEFINITION,
    create_process_capability_binding,
    create_sensor_summary_binding,
)
from app.manufacturing.process_diagnostics.contracts import (
    DiagnosticsDataError,
    DiagnosticsInputError,
    DiagnosticsQuery,
    DiagnosticsSnapshot,
    ProcessCapabilityInput,
    SensorSummaryInput,
    diagnostics_scope,
)
from app.manufacturing.process_diagnostics.handler import (
    ProcessDiagnosticsDependencies,
    process_capability_handler,
    sensor_summary_handler,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "analyst"
    roles: tuple[str, ...] = ("analyst",)


class FakePort:
    def __init__(self, snapshot: DiagnosticsSnapshot):
        self.snapshot = snapshot
        self.calls: list[DiagnosticsQuery] = []

    def fetch(
        self, query: DiagnosticsQuery, principal: Principal
    ) -> DiagnosticsSnapshot:
        self.calls.append(query)
        return self.snapshot


class FailingPort:
    def fetch(
        self, query: DiagnosticsQuery, principal: Principal
    ) -> DiagnosticsSnapshot:
        del query, principal
        raise RuntimeError("sqlite:///secret-diagnostics.db")


class UntypedPort:
    def fetch(self, query: DiagnosticsQuery, principal: Principal) -> object:
        del query, principal
        return object()


class AllowPolicy:
    def authorize(self, principal, name, scope):
        return PolicyDecision(True)


class AllowBudget:
    def claim(self, name, decoded_arguments):
        return BudgetDecision(True)

    def record_result(self, name, data, success):
        return None


def capability_row(**changes):
    row = {
        "process_step": "CMP",
        "equipment_id": "CMP-01",
        "samples": 2,
        "mean_value": 1.0,
        "sigma": 0.0,
        "min_value": 1.0,
        "max_value": 1.0,
        "cpk": None,
        "metric_name": "thickness",
        "metric_unit": "nm",
        "spec_lsl": 0.5,
        "spec_usl": 1.5,
    }
    row.update(changes)
    return row


def sensor_row(**changes):
    row = {
        "process_step": "CMP",
        "equipment_id": "CMP-01",
        "signal_name": "pressure",
        "signal_unit": "kPa",
        "samples": 2,
        "missing_samples": 0,
        "flagged_outliers": 1,
        "mean_value": 1.0,
        "min_value": 0.5,
        "max_value": 1.5,
    }
    row.update(changes)
    return row


class ProcessDiagnosticsTests(unittest.TestCase):
    today = staticmethod(lambda: date(2026, 10, 24))

    def context(self, port):
        return ToolExecutionContext(
            Principal(), "run", "call", ProcessDiagnosticsDependencies(port, self.today)
        )

    def snapshot(self, query, rows, *, scope=None):
        return DiagnosticsSnapshot(
            query,
            tuple(rows),
            ToolSource(
                "fixture",
                "test",
                ToolSourceKind.FAKE,
                scope if scope is not None else diagnostics_scope(query, Principal()),
            ),
        )

    def test_inputs_freeze_dates_reject_null_wrong_type_and_unknown_arguments(self):
        query = ProcessCapabilityInput.from_arguments({"process_step": "cmp"}).resolve(
            date(2026, 10, 24)
        )
        self.assertEqual(
            query,
            DiagnosticsQuery(
                "capability", date(2026, 7, 27), date(2026, 10, 24), "CMP"
            ),
        )
        self.assertEqual(query.end_exclusive, date(2026, 10, 25))
        for arguments in (
            {"start": None},
            {"start": 1},
            {"sql": "SELECT * FROM readings"},
        ):
            with self.assertRaises(DiagnosticsInputError):
                ProcessCapabilityInput.from_arguments(arguments)
        maximum = ProcessCapabilityInput("2024-10-24", "2026-10-24").resolve(
            date(2026, 10, 24)
        )
        self.assertEqual((maximum.end - maximum.start).days, 730)
        with self.assertRaises(DiagnosticsInputError):
            ProcessCapabilityInput("2024-10-23", "2026-10-24").resolve(
                date(2026, 10, 24)
            )
        with self.assertRaises(DiagnosticsInputError):
            SensorSummaryInput("2026-10-25", "2026-10-24").resolve(date(2026, 10, 24))

    def test_sensors_preserve_combined_exact_filters_and_schemas_are_closed(self):
        query = SensorSummaryInput(
            "2026-10-01", "2026-10-24", "cmp", "cmp-01", "Pressure"
        ).resolve(date(2026, 10, 24))
        self.assertEqual(query.process_step, "CMP")
        self.assertEqual(
            (query.equipment_id, query.signal_name), ("cmp-01", "Pressure")
        )
        self.assertEqual(
            diagnostics_scope(query, Principal()).grain, "equipment_signal"
        )
        self.assertFalse(
            PROCESS_CAPABILITY_DEFINITION.json_schema()["additionalProperties"]
        )
        self.assertFalse(
            SENSOR_SUMMARY_DEFINITION.json_schema()["additionalProperties"]
        )
        self.assertEqual(
            set(PROCESS_CAPABILITY_DEFINITION.json_schema()["properties"]),
            {"start", "end", "process_step"},
        )
        self.assertEqual(
            set(SENSOR_SUMMARY_DEFINITION.json_schema()["properties"]),
            {"start", "end", "process_step", "equipment_id", "signal_name"},
        )
        with self.assertRaises(DiagnosticsInputError):
            DiagnosticsQuery(
                "capability", date(2026, 1, 1), date(2026, 1, 1), equipment_id="CMP-01"
            )

    def test_capability_handler_rejects_inconsistent_query_scope_and_invalid_fields(
        self,
    ):
        query = ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP").resolve(
            date(2026, 10, 24)
        )
        other = DiagnosticsQuery(
            "capability", date(2026, 10, 2), date(2026, 10, 24), "CMP"
        )
        with self.assertRaises(DiagnosticsDataError):
            process_capability_handler(
                ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP"),
                self.context(FakePort(self.snapshot(other, [capability_row()]))),
            )
        bad_scope = ToolScope(
            "demo",
            query.start,
            query.end,
            process_steps=("ETCH",),
            grain="equipment_distribution",
        )
        with self.assertRaises(DiagnosticsDataError):
            process_capability_handler(
                ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP"),
                self.context(
                    FakePort(self.snapshot(query, [capability_row()], scope=bad_scope))
                ),
            )
        with self.assertRaises(DiagnosticsDataError):
            process_capability_handler(
                ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP"),
                self.context(
                    FakePort(self.snapshot(query, [capability_row(mean_value=True)]))
                ),
            )
        with self.assertRaises(DiagnosticsDataError):
            process_capability_handler(
                ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP"),
                self.context(
                    FakePort(
                        self.snapshot(query, [capability_row(process_step="ETCH")])
                    )
                ),
            )
        with self.assertRaisesRegex(DiagnosticsDataError, "unavailable") as error:
            process_capability_handler(
                ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP"),
                self.context(FailingPort()),
            )
        self.assertNotIn("secret", str(error.exception))
        with self.assertRaises(DiagnosticsDataError):
            process_capability_handler(
                ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP"),
                self.context(UntypedPort()),
            )

    def test_capability_fields_allow_negative_cpk_and_nullable_zero_sigma(self):
        query = ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP").resolve(
            date(2026, 10, 24)
        )
        result = process_capability_handler(
            ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP"),
            self.context(
                FakePort(self.snapshot(query, [capability_row(cpk=-0.25, sigma=None)]))
            ),
        )
        self.assertEqual(result.status, ToolStatus.SUCCEEDED)
        self.assertEqual(result.data[0]["cpk"], -0.25)
        zero_sigma = process_capability_handler(
            ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP"),
            self.context(FakePort(self.snapshot(query, [capability_row(sigma=0.0)]))),
        )
        self.assertEqual(zero_sigma.status, ToolStatus.SUCCEEDED)
        for invalid in (-0.01, float("nan"), float("inf"), True):
            with self.assertRaises(DiagnosticsDataError):
                process_capability_handler(
                    ProcessCapabilityInput("2026-10-01", "2026-10-24", "CMP"),
                    self.context(
                        FakePort(self.snapshot(query, [capability_row(sigma=invalid)]))
                    ),
                )

    def test_sensor_handler_filters_every_requested_field_and_all_missing_values(self):
        query = SensorSummaryInput(
            "2026-10-01", "2026-10-24", "CMP", "CMP-01", "pressure"
        ).resolve(date(2026, 10, 24))
        all_missing = sensor_row(
            signal_name="pressure",
            missing_samples=2,
            mean_value=None,
            min_value=None,
            max_value=None,
        )
        result = sensor_summary_handler(
            SensorSummaryInput("2026-10-01", "2026-10-24", "CMP", "CMP-01", "pressure"),
            self.context(FakePort(self.snapshot(query, [all_missing]))),
        )
        self.assertEqual(result.status, ToolStatus.SUCCEEDED)
        projection = project_tool_result(
            result,
            arguments={
                "start": "BAD",
                "end": "BAD",
                "process_step": "BAD",
                "equipment_id": "BAD",
                "signal_name": "pressure",
            },
        )
        self.assertEqual(
            projection.observation["arguments"],
            {
                "start": "2026-10-01",
                "end": "2026-10-24",
                "process_step": "CMP",
                "equipment_id": "CMP-01",
                "signal_name": "pressure",
            },
        )
        wrong_signal = sensor_row(signal_name="other")
        with self.assertRaises(DiagnosticsDataError):
            sensor_summary_handler(
                SensorSummaryInput(
                    "2026-10-01", "2026-10-24", "CMP", "CMP-01", "pressure"
                ),
                self.context(FakePort(self.snapshot(query, [wrong_signal]))),
            )
        with self.assertRaises(DiagnosticsDataError):
            sensor_summary_handler(
                SensorSummaryInput(
                    "2026-10-01", "2026-10-24", "CMP", "CMP-01", "pressure"
                ),
                self.context(
                    FakePort(self.snapshot(query, [sensor_row(equipment_id="CMP-02")]))
                ),
            )
        with self.assertRaises(DiagnosticsDataError):
            sensor_summary_handler(
                SensorSummaryInput(
                    "2026-10-01", "2026-10-24", "CMP", "CMP-01", "pressure"
                ),
                self.context(
                    FakePort(self.snapshot(query, [sensor_row(flagged_outliers=3)]))
                ),
            )
        for invalid in (True, float("nan"), float("inf")):
            with self.assertRaises(DiagnosticsDataError):
                sensor_summary_handler(
                    SensorSummaryInput(
                        "2026-10-01", "2026-10-24", "CMP", "CMP-01", "pressure"
                    ),
                    self.context(
                        FakePort(self.snapshot(query, [sensor_row(mean_value=invalid)]))
                    ),
                )
        with self.assertRaises(DiagnosticsDataError):
            sensor_summary_handler(
                SensorSummaryInput(
                    "2026-10-01", "2026-10-24", "CMP", "CMP-01", "pressure"
                ),
                self.context(
                    FakePort(self.snapshot(query, [sensor_row(samples=True)]))
                ),
            )
        with self.assertRaises(DiagnosticsDataError):
            sensor_summary_handler(
                SensorSummaryInput(
                    "2026-10-01", "2026-10-24", "CMP", "CMP-01", "pressure"
                ),
                self.context(
                    FakePort(self.snapshot(query, [sensor_row(mean_value=None)]))
                ),
            )

    def test_dispatcher_executes_legal_call_and_denies_unlisted_tool_once(self):
        query = ProcessCapabilityInput().resolve(date(2026, 10, 24))
        port = FakePort(self.snapshot(query, [capability_row()]))
        registry = ToolRegistry()
        registry.register_native(
            create_process_capability_binding(port, today=self.today)
        )
        registry.register_native(create_sensor_summary_binding(port, today=self.today))
        dispatcher = ToolDispatcher(
            run_id="run",
            registry=registry,
            policy=AllowPolicy(),
            budget=AllowBudget(),
            allowed_tools=frozenset({"get_process_capability"}),
        )
        context = ToolExecutionContext(Principal(), "run", "call", object())
        success = asyncio.run(
            dispatcher.dispatch("get_process_capability", {}, context)
        )
        denied = asyncio.run(dispatcher.dispatch("get_sensor_summary", {}, context))
        self.assertEqual(success.status, ToolStatus.SUCCEEDED)
        self.assertEqual(denied.status, ToolStatus.DENIED)
        self.assertEqual(len(port.calls), 1)
        self.assertEqual(port.calls[0].start, date(2026, 7, 27))
        self.assertEqual(port.calls[0].end, date(2026, 10, 24))


if __name__ == "__main__":
    unittest.main()
