from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import date

from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolScope,
    ToolSource,
    ToolSourceKind,
)
from app.manufacturing.operational_reports.binding import (
    prepare_defect_pareto,
    prepare_equipment_productivity,
    prepare_recent_excursions,
)
from app.manufacturing.operational_reports.contracts import (
    DefectParetoInput,
    EquipmentProductivityInput,
    OperationalReportDataError,
    OperationalReportInputError,
    OperationalReportQuery,
    OperationalReportSnapshot,
    RecentExcursionsInput,
    validate_defect_pareto_output,
    validate_equipment_productivity_output,
    validate_recent_excursions_output,
)
from app.manufacturing.operational_reports.handler import (
    OperationalReportsDependencies,
    defect_pareto_handler,
    equipment_productivity_handler,
    recent_excursions_handler,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "analyst"
    roles: tuple[str, ...] = ("analyst",)


class FakePort:
    def __init__(self, snapshot: object) -> None:
        self.snapshot = snapshot

    def fetch(self, query: object, principal: object) -> object:
        del query, principal
        return self.snapshot


class FailingPort:
    def fetch(self, query: object, principal: object) -> object:
        del query, principal
        raise RuntimeError("sqlite:///private-operational.db")


class OperationalReportTests(unittest.TestCase):
    today = staticmethod(lambda: date(2026, 10, 24))

    def context(
        self, port: object
    ) -> ToolExecutionContext[OperationalReportsDependencies]:
        return ToolExecutionContext(
            Principal(), "run", "call", OperationalReportsDependencies(port, self.today)
        )

    def snapshot(
        self,
        query: OperationalReportQuery,
        rows: tuple[dict[str, object], ...],
        *,
        scope: ToolScope | None = None,
    ) -> OperationalReportSnapshot:
        grains = {
            "productivity": "equipment_productivity",
            "defects": "defect_type",
            "excursions": "process_run",
        }
        return OperationalReportSnapshot(
            query,
            rows,
            ToolSource(
                "fixture",
                "test",
                ToolSourceKind.FAKE,
                scope
                or ToolScope(
                    "demo",
                    query.start,
                    query.end,
                    (query.equipment_id,) if query.equipment_id else (),
                    (query.process_step,) if query.process_step else (),
                    grain=grains[query.kind],
                ),
            ),
        )

    @staticmethod
    def productivity(**changes: object) -> dict[str, object]:
        value: dict[str, object] = {
            "equipment_id": "CMP-01",
            "recorded_minutes": 0.0,
            "productive_minutes": 0.0,
            "productive_pct": 100.0,
            "unscheduled_down_minutes": 0.0,
            "scheduled_down_minutes": 0.0,
        }
        value.update(changes)
        return value

    @staticmethod
    def defect(**changes: object) -> dict[str, object]:
        value: dict[str, object] = {
            "defect_type": "Particles",
            "process_steps": "CMP",
            "defect_count": 2,
            "affected_lots": 1,
            "share_pct": 10.0,
        }
        value.update(changes)
        return value

    @staticmethod
    def excursion(**changes: object) -> dict[str, object]:
        value: dict[str, object] = {
            "run_time": "2026-10-20T10:00:00",
            "lot_id": "L001",
            "process_step": "CMP",
            "equipment_id": "CMP-01",
            "excursion_code": "",
            "thickness_nm": None,
            "uniformity_pct": None,
            "defect_density": 0.0,
            "measurement_name": "thickness",
            "measurement_value": -1.0,
            "measurement_unit": "",
            "spec_lsl": None,
            "spec_usl": None,
        }
        value.update(changes)
        return value

    def test_inputs_are_closed_and_preserve_filter_semantics(self) -> None:
        productivity = EquipmentProductivityInput(
            "2026-10-01", "2026-10-24", "cmp", "cmp-01"
        ).resolve(self.today())
        self.assertEqual(
            (productivity.process_step, productivity.equipment_id), (None, "CMP-01")
        )
        contradictory = EquipmentProductivityInput(
            process_step="ETCH", equipment_id="cmp-01"
        ).resolve(self.today())
        self.assertEqual(
            (contradictory.process_step, contradictory.equipment_id), (None, "CMP-01")
        )
        with self.assertRaises(OperationalReportInputError):
            EquipmentProductivityInput(
                process_step="not-a-step", equipment_id="cmp-01"
            ).resolve(self.today())
        excursion = RecentExcursionsInput(
            "2026-10-01", "2026-10-24", "cmp", "cmp-01", 1
        ).resolve(self.today())
        self.assertEqual(
            (excursion.process_step, excursion.equipment_id, excursion.limit),
            ("CMP", "CMP-01", 1),
        )
        self.assertEqual(DefectParetoInput().resolve(self.today()).limit, 10)
        for input_type, arguments in (
            (EquipmentProductivityInput, {"sql": "select 1"}),
            (DefectParetoInput, {"limit": True}),
            (RecentExcursionsInput, {"limit": 101}),
            (RecentExcursionsInput, {"equipment_id": None}),
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(OperationalReportInputError),
            ):
                input_type.from_arguments(arguments)
        for value in (None, True, 1.5, "1"):
            with (
                self.subTest(defect_limit=value),
                self.assertRaises(OperationalReportInputError),
            ):
                OperationalReportQuery(
                    "defects", self.today(), self.today(), limit=value
                )
            with (
                self.subTest(excursion_limit=value),
                self.assertRaises(OperationalReportInputError),
            ):
                OperationalReportQuery(
                    "excursions", self.today(), self.today(), limit=value
                )
        with self.assertRaises(OperationalReportInputError):
            DefectParetoInput(limit=None)  # type: ignore[arg-type]

    def test_input_dates_types_and_schemas_are_defensive(self) -> None:
        resolved = EquipmentProductivityInput().resolve(self.today())
        self.assertEqual((resolved.end - resolved.start).days, 89)
        maximum = DefectParetoInput("2024-10-24", "2026-10-24").resolve(self.today())
        self.assertEqual((maximum.end - maximum.start).days, 730)
        for value in (1, True, object()):
            with (
                self.subTest(value=type(value).__name__),
                self.assertRaises(OperationalReportInputError),
            ):
                RecentExcursionsInput(equipment_id=value)
        with self.assertRaises(OperationalReportInputError):
            EquipmentProductivityInput("2024-10-23", "2026-10-24").resolve(self.today())
        with self.assertRaises(OperationalReportInputError):
            EquipmentProductivityInput(end="9999-12-31").resolve(date.max)
        first, second = DefectParetoInput.json_schema(), DefectParetoInput.json_schema()
        first["properties"]["start"]["type"] = "integer"
        self.assertEqual(second["properties"]["start"]["type"], "string")

    def test_preparation_freezes_effective_arguments_and_scope(self) -> None:
        dependencies = OperationalReportsDependencies(FakePort(None), self.today)
        context = ToolExecutionContext(Principal(), "run", "call", dependencies)
        productivity = prepare_equipment_productivity(
            EquipmentProductivityInput(process_step="cmp", equipment_id="cmp-01"),
            context,
        )
        self.assertEqual(productivity.input_value.process_step, None)
        self.assertEqual(productivity.scope.equipment_ids, ("CMP-01",))
        defects = prepare_defect_pareto(
            DefectParetoInput(process_step="cmp", limit=3), context
        )
        self.assertEqual(
            (defects.input_value.process_step, defects.input_value.limit), ("CMP", 3)
        )
        excursions = prepare_recent_excursions(
            RecentExcursionsInput(process_step="cmp", equipment_id="cmp-01", limit=2),
            context,
        )
        self.assertEqual(
            (excursions.scope.process_steps, excursions.scope.equipment_ids),
            (("CMP",), ("CMP-01",)),
        )

    def test_valid_outputs_allow_legacy_rounding_null_and_partial_pareto(self) -> None:
        productivity = [self.productivity()]
        defects = [self.defect(share_pct=10.0)]
        excursions = [self.excursion()]
        self.assertIs(
            validate_equipment_productivity_output(productivity), productivity
        )
        self.assertIs(validate_defect_pareto_output(defects), defects)
        self.assertIs(validate_recent_excursions_output(excursions), excursions)
        self.assertIsNone(self.defect(share_pct=None)["share_pct"])
        multi_process = [self.defect(process_steps="CMP,ETCH")]
        self.assertIs(validate_defect_pareto_output(multi_process), multi_process)

    def test_output_validation_rejects_nonfinite_counts_and_shape(self) -> None:
        invalid = (
            (
                validate_equipment_productivity_output,
                [self.productivity(recorded_minutes=True)],
            ),
            (
                validate_equipment_productivity_output,
                [self.productivity(productive_pct=float("inf"))],
            ),
            (validate_defect_pareto_output, [self.defect(defect_count=-1)]),
            (validate_defect_pareto_output, [self.defect(affected_lots=True)]),
            (
                validate_recent_excursions_output,
                [self.excursion(defect_density=float("nan"))],
            ),
            (validate_recent_excursions_output, [self.excursion(excursion_code=None)]),
        )
        for validator, value in invalid:
            with (
                self.subTest(value=value),
                self.assertRaises(OperationalReportDataError),
            ):
                validator(value)

    def test_handlers_validate_snapshot_scope_rows_and_errors(self) -> None:
        productivity_input = EquipmentProductivityInput(process_step="CMP")
        productivity_query = productivity_input.resolve(self.today())
        good = self.snapshot(productivity_query, (self.productivity(),))
        result = equipment_productivity_handler(
            productivity_input, self.context(FakePort(good))
        )
        self.assertEqual(
            (result.tool_name, result.row_count, result.data),
            ("get_equipment_productivity", 1, [self.productivity()]),
        )
        lower_case = self.snapshot(
            productivity_query, (self.productivity(equipment_id="cmp-01"),)
        )
        self.assertEqual(
            equipment_productivity_handler(
                productivity_input, self.context(FakePort(lower_case))
            ).row_count,
            1,
        )
        wrong_query = OperationalReportQuery(
            "productivity", date(2026, 10, 1), date(2026, 10, 24), "CMP"
        )
        invalid_ports = (
            FakePort(self.snapshot(wrong_query, (self.productivity(),))),
            FakePort(
                self.snapshot(
                    productivity_query, (self.productivity(equipment_id="ETCH-01"),)
                )
            ),
            FakePort(
                self.snapshot(
                    productivity_query,
                    (self.productivity(),),
                    scope=ToolScope(
                        "demo",
                        productivity_query.start,
                        productivity_query.end,
                        grain="wrong",
                    ),
                )
            ),
            FakePort(object()),
        )
        for port in invalid_ports:
            with self.subTest(port=port), self.assertRaises(OperationalReportDataError):
                equipment_productivity_handler(productivity_input, self.context(port))
        with self.assertRaisesRegex(OperationalReportDataError, "unavailable") as error:
            equipment_productivity_handler(
                productivity_input, self.context(FailingPort())
            )
        self.assertNotIn("private-operational", str(error.exception))

    def test_defect_and_excursion_handlers_enforce_effective_filters(self) -> None:
        defect_input = DefectParetoInput(process_step="CMP", limit=1)
        defect_query = defect_input.resolve(self.today())
        defect_pareto_handler(
            defect_input,
            self.context(FakePort(self.snapshot(defect_query, (self.defect(),)))),
        )
        with self.assertRaises(OperationalReportDataError):
            defect_pareto_handler(
                defect_input,
                self.context(
                    FakePort(
                        self.snapshot(
                            defect_query, (self.defect(process_steps="CMP,ETCH"),)
                        )
                    )
                ),
            )
        excursion_input = RecentExcursionsInput(
            process_step="CMP", equipment_id="CMP-01", limit=1
        )
        excursion_query = excursion_input.resolve(self.today())
        result = recent_excursions_handler(
            excursion_input,
            self.context(FakePort(self.snapshot(excursion_query, (self.excursion(),)))),
        )
        self.assertEqual(result.row_count, 1)
        for changed in (
            {"process_step": "ETCH"},
            {"equipment_id": "CMP-02"},
            {"run_time": "2026-07-01"},
            {"run_time": "2026-10-20garbage"},
        ):
            with (
                self.subTest(changed=changed),
                self.assertRaises(OperationalReportDataError),
            ):
                recent_excursions_handler(
                    excursion_input,
                    self.context(
                        FakePort(
                            self.snapshot(excursion_query, (self.excursion(**changed),))
                        )
                    ),
                )


if __name__ == "__main__":
    unittest.main()
