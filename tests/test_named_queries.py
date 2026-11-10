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
from app.tools.named_queries.binding import create_named_query_binding
from app.tools.named_queries.contracts import (
    EquipmentEventsInput,
    EquipmentExcursionsInput,
    LotQueryInput,
    NamedQuery,
    NamedQueryDataError,
    NamedQueryInputError,
    NamedQuerySnapshot,
    ProductYieldInput,
    named_query_scope,
    validate_named_query_output,
)
from app.tools.named_queries.handler import (
    NamedQueryDependencies,
    named_query_handler,
)


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "demo"
    user_id: str = "analyst"
    roles: tuple[str, ...] = ("analyst",)


class Port:
    def __init__(self, snapshot: object) -> None:
        self.snapshot = snapshot

    def fetch(self, query: object, principal: object) -> object:
        del query, principal
        return self.snapshot


class FailingPort:
    def fetch(self, query: object, principal: object) -> object:
        del query, principal
        raise RuntimeError("sqlite:///secret.db")


class NamedQueryTests(unittest.TestCase):
    as_of = date(2026, 10, 24)

    def context(
        self, port: object, kind: str
    ) -> ToolExecutionContext[NamedQueryDependencies]:
        return ToolExecutionContext(
            Principal(), "run", "call", NamedQueryDependencies(port, kind, self.as_of)
        )

    def snapshot(
        self, query: NamedQuery, rows: tuple[dict[str, object], ...]
    ) -> NamedQuerySnapshot:
        return NamedQuerySnapshot(
            query,
            rows,
            ToolSource(
                "fixture",
                "test",
                ToolSourceKind.FAKE,
                named_query_scope(query, Principal()),
            ),
        )

    @staticmethod
    def rows() -> dict[str, dict[str, object]]:
        return {
            "product_yield": {
                "product": "P",
                "technology_nm": 7,
                "lots": 1,
                "wafers": 1,
                "yield_pct": None,
            },
            "equipment_events": {
                "equipment_id": "EQP-1",
                "event_time": "2026-10-20T01:00:00",
                "event_type": "",
                "duration_minutes": 0.0,
                "severity": "",
                "reason": "",
            },
            "equipment_excursions": {
                "lot_id": "LOT-1",
                "run_time": "2026-10-20T01:00:00",
                "process_step": "CMP",
                "equipment_id": "EQP-1",
                "excursion_code": "",
                "measurement_name": "",
                "measurement_value": None,
                "measurement_unit": "",
                "spec_lsl": None,
                "spec_usl": None,
            },
            "lot_identity": {
                "lot_id": "LOT-1",
                "product": "P",
                "technology_nm": 7,
                "route": "",
                "priority": "",
                "start_time": "2020-01-01",
                "complete_time": None,
                "status": "",
                "wafer_count": 1,
                "good_wafers": 0,
                "yield_rate": 0.0,
                "cycle_time_hours": 0.0,
                "hold_hours": 0.0,
            },
            "lot_process_history": {
                "lot_id": "LOT-1",
                "operation_seq": 1,
                "layer_name": "",
                "process_step": "CMP",
                "equipment_id": "EQP-1",
                "chamber": "",
                "recipe": "",
                "run_time": "2020-01-01",
                "queue_hours": 0.0,
                "rework_flag": False,
            },
            "lot_excursions": {
                "lot_id": "LOT-1",
                "operation_seq": 1,
                "run_time": "2020-01-01",
                "process_step": "CMP",
                "equipment_id": "EQP-1",
                "excursion_code": "",
                "measurement_name": "",
                "measurement_value": None,
                "measurement_unit": "",
                "spec_lsl": None,
                "spec_usl": None,
            },
            "lot_defects": {
                "lot_id": "LOT-1",
                "detected_time": "2020-01-01",
                "process_step": "CMP",
                "defect_type": "",
                "count": 0,
                "disposition": "",
            },
            "lot_wafer_maps": {
                "lot_id": "LOT-1",
                "wafer_no": 1,
                "detected_time": "2020-01-01",
                "process_step": "CMP",
                "equipment_id": "EQP-1",
                "pattern_class": "",
                "tested_dies": 1,
                "failed_dies": 0,
            },
        }

    def test_inputs_are_closed_strict_and_resolve_fixed_defaults(self) -> None:
        query = ProductYieldInput(product=" PROD ").resolve("product_yield", self.as_of)
        self.assertEqual((query.product, (query.end - query.start).days), ("PROD", 89))
        explicit = ProductYieldInput("2026-10-01", "2026-10-24").resolve(
            "product_yield", self.as_of
        )
        self.assertEqual(
            (explicit.start, explicit.end), (date(2026, 10, 1), self.as_of)
        )
        self.assertEqual(
            EquipmentExcursionsInput(process_step="cmp")
            .resolve("equipment_excursions", self.as_of)
            .process_step,
            "CMP",
        )
        self.assertEqual(
            LotQueryInput(" LOT-1 ").resolve("lot_identity", self.as_of).lot_id, "LOT-1"
        )
        for model, arguments in (
            (ProductYieldInput, {"sql": "select 1"}),
            (EquipmentEventsInput, {"start": "20261024"}),
            (LotQueryInput, {"lot_id": None}),
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(NamedQueryInputError),
            ):
                model.from_arguments(arguments)
        with self.assertRaises(NamedQueryInputError):
            EquipmentExcursionsInput.from_arguments(
                {"process_step": "unknown"}
            ).resolve("equipment_excursions", self.as_of)
        with self.assertRaises(NamedQueryInputError):
            NamedQuery([], self.as_of, self.as_of)  # type: ignore[arg-type]
        with self.assertRaises(NamedQueryInputError):
            NamedQuery("product_yield", True, self.as_of)  # type: ignore[arg-type]
        with self.assertRaises(NamedQueryInputError):
            NamedQuery("lot_identity", self.as_of, self.as_of, lot_id="LOT-1")
        with self.assertRaises(NamedQueryInputError):
            NamedQueryDependencies(Port(None), "bad", self.as_of)
        with self.assertRaises(NamedQueryInputError):
            ProductYieldInput().resolve("product_yield", date.max)

    def test_handler_validates_scope_date_rows_and_deepcopies(self) -> None:
        input_value = EquipmentEventsInput("2026-10-01", "2026-10-24", "EQP-1")
        query = input_value.resolve("equipment_events", self.as_of)
        row = self.rows()["equipment_events"]
        result = named_query_handler(
            input_value, self.context(Port(self.snapshot(query, (row,))), query.kind)
        )
        self.assertEqual(
            (result.tool_name, result.row_count), ("get_equipment_event_timeline", 1)
        )
        result.data[0]["reason"] = "changed"  # type: ignore[index]
        self.assertEqual(row["reason"], "")
        wrong = dict(row, event_time="2026-09-30T23:59:00")
        with self.assertRaises(NamedQueryDataError):
            named_query_handler(
                input_value,
                self.context(Port(self.snapshot(query, (wrong,))), query.kind),
            )
        wrong_equipment = dict(row, equipment_id="EQP-2")
        with self.assertRaises(NamedQueryDataError):
            named_query_handler(
                input_value,
                self.context(
                    Port(self.snapshot(query, (wrong_equipment,))), query.kind
                ),
            )
        mismatched = NamedQuery("equipment_events", date(2026, 10, 2), self.as_of)
        with self.assertRaises(NamedQueryDataError):
            named_query_handler(
                input_value,
                self.context(Port(self.snapshot(mismatched, (row,))), query.kind),
            )
        wrong_scope = NamedQuerySnapshot(
            query,
            (row,),
            ToolSource("fixture", "test", ToolSourceKind.FAKE, ToolScope("demo")),
        )
        with self.assertRaises(NamedQueryDataError):
            named_query_handler(
                input_value, self.context(Port(wrong_scope), query.kind)
            )
        with self.assertRaisesRegex(NamedQueryDataError, "unavailable") as error:
            named_query_handler(input_value, self.context(FailingPort(), query.kind))
        self.assertNotIn("secret", str(error.exception))

    def test_lot_queries_are_all_time_and_prepare_keeps_call_input(self) -> None:
        binding = create_named_query_binding(
            "get_lot_defect_history", Port(None), as_of=self.as_of
        )
        input_value = LotQueryInput(" LOT-1 ")
        prepared = binding.prepare(input_value, self.context(Port(None), "lot_defects"))
        self.assertIs(prepared.input_value, input_value)
        self.assertEqual(
            (prepared.scope.start_date, prepared.scope.lot_ids), (None, ("LOT-1",))
        )
        lot_input = LotQueryInput("LOT-1")
        lot_query = lot_input.resolve("lot_defects", self.as_of)
        result = named_query_handler(
            lot_input,
            self.context(
                Port(self.snapshot(lot_query, (self.rows()["lot_defects"],))),
                "lot_defects",
            ),
        )
        self.assertEqual(result.row_count, 1)
        product_input = ProductYieldInput(product="P")
        product_query = product_input.resolve("product_yield", self.as_of)
        wrong_product = dict(self.rows()["product_yield"], product="OTHER")
        with self.assertRaises(NamedQueryDataError):
            named_query_handler(
                product_input,
                self.context(
                    Port(self.snapshot(product_query, (wrong_product,))),
                    "product_yield",
                ),
            )

    def test_all_fixed_output_shapes_reject_malformed_values(self) -> None:
        for kind, row in self.rows().items():
            with self.subTest(kind=kind):
                value = [row]
                self.assertIs(validate_named_query_output(kind, value), value)
                malformed = dict(row)
                malformed["hidden"] = "no"
                with self.assertRaises(NamedQueryDataError):
                    validate_named_query_output(kind, [malformed])
        invalid = self.rows()["lot_defects"]
        invalid["count"] = True
        with self.assertRaises(NamedQueryDataError):
            validate_named_query_output("lot_defects", [invalid])
        invalid_cases = (
            ("product_yield", "technology_nm", "7"),
            ("product_yield", "lots", 0),
            ("equipment_events", "duration_minutes", -0.1),
            ("lot_identity", "yield_rate", 1.1),
            ("lot_identity", "good_wafers", 2),
            ("lot_process_history", "operation_seq", 0),
            ("lot_wafer_maps", "failed_dies", 2),
            ("lot_defects", "detected_time", "not-a-date"),
        )
        for kind, field, replacement in invalid_cases:
            with self.subTest(kind=kind, field=field):
                row = self.rows()[kind]
                row[field] = replacement
                with self.assertRaises(NamedQueryDataError):
                    validate_named_query_output(kind, [row])
        with self.assertRaises(NamedQueryDataError):
            validate_named_query_output([], [])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
