import unittest
from dataclasses import dataclass
from datetime import date

from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolScope,
    ToolSource,
    ToolSourceKind,
)
from app.manufacturing.production_reports.contracts import (
    FabOverviewInput,
    ProcessPassRateInput,
    ProductionReportDataError,
    ProductionReportInputError,
    ProductionReportQuery,
    ProductionReportSnapshot,
    YieldTrendInput,
    validate_fab_overview_output,
    validate_process_pass_rate_output,
    validate_yield_trend_output,
)
from app.manufacturing.production_reports.handler import (
    ProductionReportsDependencies,
    fab_overview_handler,
    process_pass_rate_handler,
    yield_trend_handler,
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
        raise RuntimeError("sqlite:///secret-production.db")


class ProductionReportContractTests(unittest.TestCase):
    today = staticmethod(lambda: date(2026, 10, 24))

    def context(
        self, port: object
    ) -> ToolExecutionContext[ProductionReportsDependencies]:
        return ToolExecutionContext(
            Principal(), "run", "call", ProductionReportsDependencies(port, self.today)
        )

    def snapshot(
        self,
        query: ProductionReportQuery,
        data: dict[str, object] | tuple[dict[str, object], ...],
        *,
        scope: ToolScope | None = None,
    ) -> ProductionReportSnapshot:
        grains = {
            "overview": "fab_overview",
            "yield": "weekly_yield",
            "pass_rate": "process_pass_rate",
        }
        return ProductionReportSnapshot(
            query,
            data,
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
    def overview(**changes: object) -> dict[str, object]:
        value: dict[str, object] = {
            "lots": 1,
            "wafers": 10,
            "good_wafers": 9,
            "yield_pct": 90.0,
            "avg_cycle_hours": 1.0,
            "avg_hold_hours": 0.0,
            "held_lots": 0,
            "excursions": 0,
            "start": "2026-10-01",
            "end": "2026-10-24",
        }
        value.update(changes)
        return value

    def test_inputs_are_closed_and_resolve(self):
        self.assertEqual(
            ProcessPassRateInput.from_arguments(
                {"process_step": "cmp", "equipment_id": "cmp-1"}
            )
            .resolve(date(2026, 10, 24))
            .equipment_id,
            "CMP-1",
        )
        self.assertEqual(
            YieldTrendInput.from_arguments({"product": "P1"})
            .resolve(date(2026, 10, 24))
            .product,
            "P1",
        )
        for arguments in ({"sql": "select 1"}, {"process_step": None}):
            with self.assertRaises(ProductionReportInputError):
                ProcessPassRateInput.from_arguments(arguments).resolve(
                    date(2026, 10, 24)
                )

    def test_output_shapes_allow_legacy_nulls(self):
        value = {
            "lots": 0,
            "wafers": None,
            "good_wafers": None,
            "yield_pct": None,
            "avg_cycle_hours": None,
            "avg_hold_hours": None,
            "held_lots": None,
            "excursions": 0,
            "start": "2026-01-01",
            "end": "2026-01-02",
        }
        self.assertIs(validate_fab_overview_output(value), value)
        rows = [
            {
                "period": "2026-00",
                "week_start": "2026-01-01",
                "lots": 1,
                "yield_pct": None,
                "cycle_hours": None,
            }
        ]
        self.assertIs(validate_yield_trend_output(rows), rows)

    def test_typed_inputs_and_schemas_are_defensive(self):
        for value in (1, True, object()):
            with (
                self.subTest(value=type(value).__name__),
                self.assertRaises(ProductionReportInputError),
            ):
                YieldTrendInput(product=value)
        first, second = FabOverviewInput.json_schema(), FabOverviewInput.json_schema()
        first["properties"]["start"]["type"] = "integer"
        self.assertEqual(second["properties"]["start"]["type"], "string")
        self.assertEqual(
            FabOverviewInput().resolve(date(2026, 10, 24)).start.isoformat(),
            "2026-07-27",
        )
        with self.assertRaises(ProductionReportInputError):
            FabOverviewInput(end="9999-12-31").resolve(date.max)

    def test_output_rejects_invalid_counts_and_rows(self):
        with self.assertRaises(ProductionReportDataError):
            validate_fab_overview_output({"lots": 0})
        with self.assertRaises(ProductionReportDataError):
            validate_yield_trend_output(
                [
                    {
                        "period": "2026-00",
                        "week_start": "2026-01-01",
                        "lots": 1,
                        "yield_pct": float("nan"),
                        "cycle_hours": 1.0,
                    }
                ]
            )
        with self.assertRaises(ProductionReportDataError):
            validate_process_pass_rate_output(
                [
                    {
                        "process_step": "CMP",
                        "equipment_id": None,
                        "runs": 1,
                        "passed_runs": 2,
                        "pass_pct": 100.0,
                    }
                ]
            )

    def test_input_date_boundaries_and_closed_arguments(self):
        maximum = FabOverviewInput("2024-10-24", "2026-10-24").resolve(
            date(2026, 10, 24)
        )
        self.assertEqual((maximum.end - maximum.start).days, 730)
        for arguments in (
            {"sql": "select 1"},
            {"start": None},
            {"start": 1},
            {"start": "2026/10/01"},
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(ProductionReportInputError),
            ):
                FabOverviewInput.from_arguments(arguments).resolve(date(2026, 10, 24))
        with self.assertRaises(ProductionReportInputError):
            FabOverviewInput("2024-10-23", "2026-10-24").resolve(date(2026, 10, 24))
        with self.assertRaises(ProductionReportInputError):
            ProcessPassRateInput().resolve(date(2026, 10, 24))

    def test_handler_rejects_bad_snapshot_scope_and_source_exception(self):
        input_value = FabOverviewInput("2026-10-01", "2026-10-24")
        query = input_value.resolve(date(2026, 10, 24))
        other = ProductionReportQuery("overview", date(2026, 10, 2), date(2026, 10, 24))
        ports = (
            FakePort(self.snapshot(other, self.overview())),
            FakePort(
                self.snapshot(
                    query,
                    self.overview(),
                    scope=ToolScope("demo", query.start, query.end, grain="wrong"),
                )
            ),
            FakePort(self.snapshot(query, {"start": query.start.isoformat()})),
            FakePort(self.snapshot(query, self.overview(end="bad-date"))),
            FakePort(object()),
        )
        for port in ports:
            with (
                self.subTest(port=type(port).__name__),
                self.assertRaises(ProductionReportDataError),
            ):
                fab_overview_handler(input_value, self.context(port))
        with self.assertRaisesRegex(ProductionReportDataError, "unavailable") as error:
            fab_overview_handler(input_value, self.context(FailingPort()))
        self.assertNotIn("secret-production", str(error.exception))

    def test_handler_rejects_outside_rows_and_product_query_mismatch(self):
        yield_input = YieldTrendInput("2026-10-01", "2026-10-24", "P1")
        yield_query = yield_input.resolve(date(2026, 10, 24))
        outside = {
            "period": "2026-39",
            "week_start": "2026-09-30",
            "lots": 1,
            "yield_pct": 1.0,
            "cycle_hours": 1.0,
        }
        with self.assertRaises(ProductionReportDataError):
            yield_trend_handler(
                yield_input,
                self.context(FakePort(self.snapshot(yield_query, (outside,)))),
            )
        mismatched_product = ProductionReportQuery(
            "yield", yield_query.start, yield_query.end, product="P2"
        )
        with self.assertRaises(ProductionReportDataError):
            yield_trend_handler(
                yield_input,
                self.context(FakePort(self.snapshot(mismatched_product, ()))),
            )
        pass_input = ProcessPassRateInput("2026-10-01", "2026-10-24", "CMP")
        pass_query = pass_input.resolve(date(2026, 10, 24))
        for row in (
            {
                "process_step": "ETCH",
                "equipment_id": None,
                "runs": 1,
                "passed_runs": 1,
                "pass_pct": 100.0,
            },
            {
                "process_step": "CMP",
                "equipment_id": "CMP-01",
                "runs": 1,
                "passed_runs": 1,
                "pass_pct": 100.0,
            },
        ):
            with self.subTest(row=row), self.assertRaises(ProductionReportDataError):
                process_pass_rate_handler(
                    pass_input,
                    self.context(FakePort(self.snapshot(pass_query, (row,)))),
                )
