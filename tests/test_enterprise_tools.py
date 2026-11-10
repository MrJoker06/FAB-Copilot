from __future__ import annotations

import math
import unittest
from copy import deepcopy
from dataclasses import dataclass
from datetime import date

from app.agent_runtime.tools.contracts import (
    ToolExecutionContext,
    ToolScope,
    ToolSource,
    ToolSourceKind,
)
from app.tools.enterprise_data.binding import (
    create_enterprise_manifest_binding,
    create_enterprise_sample_binding,
    create_enterprise_summary_binding,
)
from app.tools.enterprise_data.contracts import (
    EnterpriseDataError,
    EnterpriseInputError,
    EnterpriseManifestInput,
    EnterpriseSampleInput,
    EnterpriseSnapshot,
    EnterpriseSummaryInput,
    EnterpriseWindow,
    enterprise_scope,
)
from app.tools.enterprise_data.handler import EnterpriseToolsDependencies


@dataclass(frozen=True)
class Principal:
    tenant_id: str = "tenant-a"
    user_id: str = "user-a"
    roles: tuple[str, ...] = ("engineer",)


class Port:
    def __init__(self, data: dict[str, object], *, tenant: str = "tenant-a") -> None:
        self.data = data
        self.tenant = tenant
        self.calls = 0

    def fetch(self, query: object, principal: Principal) -> EnterpriseSnapshot:
        self.calls += 1
        return EnterpriseSnapshot(
            query,
            deepcopy(self.data),
            ToolSource(
                "fake:test",
                "test",
                ToolSourceKind.FAKE,
                enterprise_scope(query, principal),
            ),
        )


class MismatchPort(Port):
    def __init__(self, data: dict[str, object], mode: str) -> None:
        super().__init__(data)
        self.mode = mode

    def fetch(self, query: object, principal: Principal) -> EnterpriseSnapshot:
        snapshot = super().fetch(query, principal)
        if self.mode == "query":
            return EnterpriseSnapshot(
                EnterpriseManifestInput().resolve(EnterpriseWindow(date(2026, 10, 28))),
                snapshot.data,
                snapshot.source,
            )
        return EnterpriseSnapshot(
            snapshot.query,
            snapshot.data,
            ToolSource(
                snapshot.source.source_ref,
                snapshot.source.adapter_id,
                snapshot.source.source_kind,
                ToolScope("other", None, None, (), (), grain="other"),
            ),
        )


class EnterpriseToolsTests(unittest.TestCase):
    window = EnterpriseWindow(date(2026, 10, 28))

    def context(self, port: Port) -> ToolExecutionContext[EnterpriseToolsDependencies]:
        return ToolExecutionContext(
            Principal(), "run", "call", EnterpriseToolsDependencies(port, self.window)
        )

    @staticmethod
    def manifest() -> dict[str, object]:
        return {
            "provider": "fixture",
            "simulated": True,
            "tenant_id": "tenant-a",
            "virtual_scale": {"lots": 1, "process-runs": 18, "sensor-events": 144},
            "entities": {
                "lots": {"path": "/lots", "primary_key": "lot_id"},
                "process-runs": {"path": "/runs", "primary_key": "run_id"},
                "sensor-events": {"path": "/sensors", "primary_key": "reading_id"},
            },
            "analytics": {
                "summary_path": "/summary",
                "semantics": "deterministic_projection",
                "supports": ["date_range", "process_step", "equipment_id"],
            },
            "pagination": {
                "strategy": "opaque_fixture_cursor",
                "default_limit": 20,
                "max_limit": 50,
            },
            "retention_days": 730,
            "partition_recommendation": ["tenant_id", "event_date", "process_step"],
            "data_classification": "synthetic_non_production",
        }

    def summary(
        self, input_value: EnterpriseSummaryInput | None = None
    ) -> dict[str, object]:
        query = (input_value or EnterpriseSummaryInput()).resolve(self.window)
        return {
            "provider": "fixture",
            "simulated": True,
            "tenant_id": "tenant-a",
            "query": {
                "filters": query.filter_dict(),
                "effective_start": query.effective_start.isoformat(),
                "effective_end": query.effective_end.isoformat(),
                "query_id": "id",
            },
            "aggregation": {
                "semantics": "deterministic_projection",
                "exact": False,
                "description": "fixture",
            },
            "totals": {
                "lots": 1,
                "completed_lots": 1,
                "wafers": 25,
                "process_runs": 18,
                "sensor_events": 144,
            },
            "kpis": {
                "yield_pct": 95.0,
                "process_pass_rate_pct": 96.0,
                "avg_cycle_hours": 10.0,
                "hold_rate_pct": 1.0,
                "excursion_rate_pct": 0.5,
                "excursion_runs": 0,
                "sensor_missing_pct": 0.1,
                "sensor_outlier_pct": 0.2,
            },
            "equipment": [
                {
                    "equipment_id": query.filter_dict().get("equipment_id", "CMP-01"),
                    "projected_runs": 18,
                    "pass_rate_pct": 96.0,
                    "excursion_rate_pct": 0.5,
                    "health_score": 99.0,
                    "risk": "stable",
                }
            ],
            "lineage": {
                "source": "fixture",
                "classification": "synthetic_non_production",
                "generated_from": ["fixture"],
                "as_of": query.as_of.isoformat() + "T00:00:00+00:00",
                "freshness": "daily",
            },
        }

    def sample(self, input_value: EnterpriseSampleInput) -> dict[str, object]:
        query = input_value.resolve(self.window)
        stamp = query.effective_end.isoformat() + "T00:00:00+00:00"
        filters = query.filter_dict()
        if query.entity == "lots":
            record = {
                "tenant_id": "tenant-a",
                "lot_id": "L1",
                "product": filters.get("product", "Nova-P1"),
                "technology_nm": 28,
                "route": "R",
                "priority": "Normal",
                "start_time": stamp,
                "status": filters.get("status", "Completed"),
                "wafer_count": 25,
                "good_wafers": 24,
                "yield_rate": 0.96,
                "cycle_time_hours": 72.0,
                "synthetic": True,
            }
        elif query.entity == "process-runs":
            record = {
                "tenant_id": "tenant-a",
                "run_id": "R1",
                "lot_id": "L1",
                "operation_seq": 1,
                "process_step": filters.get("process_step", "CMP"),
                "equipment_id": filters.get("equipment_id", "CMP-01"),
                "chamber": "C1",
                "recipe": "R",
                "run_time": stamp,
                "measurement_name": "metric",
                "measurement_value": 1.0,
                "measurement_unit": "u",
                "pass_flag": 1,
                "synthetic": True,
            }
        else:
            record = {
                "tenant_id": "tenant-a",
                "reading_id": "S1",
                "lot_id": "L1",
                "process_step": filters.get("process_step", "CMP"),
                "equipment_id": filters.get("equipment_id", "CMP-01"),
                "chamber": "C1",
                "sample_time": stamp,
                "signal_name": filters.get("signal_name", "RF power"),
                "signal_value": 1.0,
                "signal_unit": "W",
                "is_missing": 0,
                "is_outlier": 0,
                "synthetic": True,
            }
        return {
            "provider": "fixture",
            "simulated": True,
            "tenant_id": "tenant-a",
            "entity": query.entity,
            "filters": filters,
            "records": [record],
            "page": {
                "count": 1,
                "limit": query.limit,
                "position": 0,
                "estimated_total": 1,
                "next_cursor": None,
            },
        }

    def test_inputs_are_closed_typed_and_clip_dates(self) -> None:
        sample = EnterpriseSampleInput("lots").resolve(self.window)
        self.assertEqual(sample.filter_dict(), {})
        self.assertEqual(sample.effective_start, date(2024, 10, 29))
        self.assertEqual(sample.effective_end, self.window.as_of)
        self.assertEqual(
            EnterpriseSummaryInput().resolve(self.window).effective_start,
            date(2026, 7, 31),
        )
        clipped = EnterpriseSampleInput(
            "lots", start="2023-01-01", end="2027-01-01"
        ).resolve(self.window)
        self.assertEqual(
            (clipped.effective_start, clipped.effective_end),
            (date(2024, 10, 29), date(2026, 10, 28)),
        )
        for value in ("20261028", "2026-W44-3", "2026-2-3"):
            with self.subTest(value=value), self.assertRaises(EnterpriseInputError):
                EnterpriseSampleInput("lots", start=value)
        for arguments in (
            {},
            {"entity": None},
            {"entity": "lots", "cursor": "x"},
            {"entity": []},
            {"entity": {}},
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(EnterpriseInputError),
            ):
                EnterpriseSampleInput.from_arguments(arguments)
        for kwargs in (
            {"entity": "lots", "limit": True},
            {"entity": "lots", "process_step": "ETCH"},
            {"entity": "sensor-events", "product": "Nova-P1"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(EnterpriseInputError):
                EnterpriseSampleInput(**kwargs)
        with self.assertRaises(EnterpriseInputError):
            EnterpriseSampleInput("lots", start="2020-01-01", end="2020-01-02").resolve(
                self.window
            )
        schema = EnterpriseSampleInput.json_schema()
        schema["properties"]["entity"]["enum"].append("bad")
        self.assertNotIn(
            "bad", EnterpriseSampleInput.json_schema()["properties"]["entity"]["enum"]
        )

    def test_all_handlers_accept_complete_contracts(self) -> None:
        manifest_port = Port(self.manifest())
        manifest = create_enterprise_manifest_binding(manifest_port, window=self.window)
        self.assertEqual(
            manifest.handler(
                EnterpriseManifestInput(), self.context(manifest_port)
            ).row_count,
            1,
        )
        summary_input = EnterpriseSummaryInput(
            process_step="CMP", equipment_id="CMP-01"
        )
        summary_port = Port(self.summary(summary_input))
        summary = create_enterprise_summary_binding(summary_port, window=self.window)
        self.assertEqual(
            summary.handler(summary_input, self.context(summary_port)).row_count, 1
        )
        for entity in ("lots", "process-runs", "sensor-events"):
            input_value = EnterpriseSampleInput(entity)
            port = Port(self.sample(input_value))
            binding = create_enterprise_sample_binding(port, window=self.window)
            with self.subTest(entity=entity):
                self.assertEqual(
                    binding.prepare(input_value, self.context(port)).input_value,
                    input_value,
                )
                result = binding.handler(input_value, self.context(port))
                self.assertEqual(result.row_count, 1)
                self.assertEqual(result.data, self.sample(input_value))
                result.data["records"].clear()
                self.assertEqual(len(port.data["records"]), 1)

    def test_scope_is_canonical_and_prepare_preserves_identity(self) -> None:
        value = EnterpriseSummaryInput(process_step="CMP", equipment_id="CMP-01")
        query = value.resolve(self.window)
        self.assertEqual(
            query.filters,
            (("equipment_id", "CMP-01"), ("process_step", "CMP")),
        )
        port = Port(self.summary(value))
        binding = create_enterprise_summary_binding(port, window=self.window)
        prepared = binding.prepare(value, self.context(port))
        self.assertIs(prepared.input_value, value)
        self.assertEqual(prepared.scope, enterprise_scope(query, Principal()))

    def test_invalid_source_bodies_and_scope_are_sanitized(self) -> None:
        input_value = EnterpriseSampleInput("lots")
        cases = []
        nan = self.sample(input_value)
        nan["records"][0]["yield_rate"] = math.nan
        cases.append(nan)
        count = self.sample(input_value)
        count["page"]["count"] = 2
        cases.append(count)
        wrong_filter = self.sample(input_value)
        wrong_filter["filters"] = {"product": "bad"}
        cases.append(wrong_filter)
        wrong_tenant = self.sample(input_value)
        wrong_tenant["tenant_id"] = "other"
        cases.append(wrong_tenant)
        for data in cases:
            port = Port(data)
            binding = create_enterprise_sample_binding(port, window=self.window)
            with self.subTest(data=data), self.assertRaises(EnterpriseDataError):
                binding.handler(input_value, self.context(port))

    def test_each_contract_rejects_own_nested_data_and_snapshot_identity(self) -> None:
        manifest = self.manifest()
        manifest["entities"]["lots"] = {"path": "/lots"}
        manifest_port = Port(manifest)
        with self.assertRaises(EnterpriseDataError):
            create_enterprise_manifest_binding(
                manifest_port, window=self.window
            ).handler(EnterpriseManifestInput(), self.context(manifest_port))

        summary_input = EnterpriseSummaryInput(
            process_step="CMP", equipment_id="CMP-01"
        )
        summary = self.summary(summary_input)
        summary["lineage"]["source"] = "wrong"
        summary_port = Port(summary)
        with self.assertRaises(EnterpriseDataError):
            create_enterprise_summary_binding(summary_port, window=self.window).handler(
                summary_input, self.context(summary_port)
            )

        sample_input = EnterpriseSampleInput(
            "process-runs", process_step="CMP", equipment_id="CMP-01"
        )
        sample = self.sample(sample_input)
        sample["records"][0]["equipment_id"] = "OTHER"
        sample_port = Port(sample)
        with self.assertRaises(EnterpriseDataError):
            create_enterprise_sample_binding(sample_port, window=self.window).handler(
                sample_input, self.context(sample_port)
            )

        for entity, kwargs, field, bad_value in (
            ("lots", {"product": "Nova-P1", "status": "Completed"}, "product", "Other"),
            ("lots", {"product": "Nova-P1", "status": "Completed"}, "status", "Hold"),
            (
                "process-runs",
                {"process_step": "CMP", "equipment_id": "CMP-01"},
                "process_step",
                "ETCH",
            ),
            (
                "sensor-events",
                {
                    "process_step": "CMP",
                    "equipment_id": "CMP-01",
                    "signal_name": "RF power",
                },
                "signal_name",
                "Other",
            ),
            (
                "sensor-events",
                {
                    "process_step": "CMP",
                    "equipment_id": "CMP-01",
                    "signal_name": "RF power",
                },
                "synthetic",
                False,
            ),
        ):
            value = EnterpriseSampleInput(entity, **kwargs)
            body = self.sample(value)
            body["records"][0][field] = bad_value
            port = Port(body)
            with (
                self.subTest(entity=entity, field=field),
                self.assertRaises(EnterpriseDataError),
            ):
                create_enterprise_sample_binding(port, window=self.window).handler(
                    value, self.context(port)
                )

        for mode in ("query", "scope"):
            port = MismatchPort(self.sample(EnterpriseSampleInput("lots")), mode)
            with self.subTest(mode=mode), self.assertRaises(EnterpriseDataError):
                create_enterprise_sample_binding(port, window=self.window).handler(
                    EnterpriseSampleInput("lots"), self.context(port)
                )

    def test_invalid_input_never_contacts_port(self) -> None:
        port = Port(self.sample(EnterpriseSampleInput("lots")))
        with self.assertRaises(EnterpriseInputError):
            EnterpriseSampleInput.from_arguments({"entity": "lots", "limit": True})
        self.assertEqual(port.calls, 0)


if __name__ == "__main__":
    unittest.main()
