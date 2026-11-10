"""Ready and Loop acceptance checks for the enterprise-data demo."""

from __future__ import annotations

import argparse
import asyncio
import json
import unittest
from unittest.mock import patch

from app.agent_runtime.execution.runtime_contracts import ModelRequest
from app.bootstrap import enterprise_tools_demo as demo
from app.demo_data.tool_sources.enterprise_data import (
    FakeEnterpriseToolsAdapter,
)
from app.tools.enterprise_data.data_source import (
    ProviderEnterpriseToolsAdapter,
)
from app.tools.enterprise_data.contracts import EnterpriseDataError


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "mode": "ready",
        "adapter": "fake",
        "tenant_id": "demo",
        "source_tenant_id": "demo",
        "role": "analyst",
        "tool": "get_enterprise_data_manifest",
        "arguments": "{}",
        "as_of": "2026-10-24",
        "timeout_ms": 1000,
        "max_tool_calls": 1,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _manifest() -> dict[str, object]:
    return {
        "provider": "fake-enterprise-v1",
        "simulated": True,
        "tenant_id": "demo",
        "virtual_scale": {"lots": 1, "process-runs": 18, "sensor-events": 144},
        "entities": {
            "lots": {"path": "/api/enterprise/data/lots", "primary_key": "lot_id"},
            "process-runs": {
                "path": "/api/enterprise/data/process-runs",
                "primary_key": "run_id",
            },
            "sensor-events": {
                "path": "/api/enterprise/data/sensor-events",
                "primary_key": "reading_id",
            },
        },
        "analytics": {
            "summary_path": "/api/enterprise/data/summary",
            "semantics": "deterministic_projection",
            "supports": ["date_range", "process_step", "equipment_id"],
        },
        "pagination": {
            "strategy": "opaque_fixture_cursor",
            "default_limit": 100,
            "max_limit": 500,
        },
        "retention_days": 730,
        "partition_recommendation": ["tenant_id", "event_date", "process_step"],
        "data_classification": "synthetic_non_production",
    }


def _summary() -> dict[str, object]:
    return {
        "provider": "fake-enterprise-v1",
        "simulated": True,
        "tenant_id": "demo",
        "query": {
            "filters": {"process_step": "CMP", "equipment_id": "CMP-01"},
            "effective_start": "2026-07-27",
            "effective_end": "2026-10-24",
            "query_id": "fake-aggregate-001",
        },
        "aggregation": {
            "semantics": "deterministic_projection",
            "exact": False,
            "description": "Explicit fake deterministic projection; not a company observation.",
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
                "equipment_id": "CMP-01",
                "projected_runs": 18,
                "pass_rate_pct": 96.0,
                "excursion_rate_pct": 0.5,
                "health_score": 99.0,
                "risk": "stable",
            }
        ],
        "lineage": {
            "source": "fake-enterprise-v1",
            "classification": "synthetic_non_production",
            "generated_from": [
                "tenant_id",
                "date_window",
                "process_step",
                "equipment_id",
                "fixture",
            ],
            "as_of": "2026-10-24T00:00:00+00:00",
            "freshness": "deterministic_daily_snapshot",
        },
    }


def _lot_sample() -> dict[str, object]:
    return {
        "provider": "fake-enterprise-v1",
        "simulated": True,
        "tenant_id": "demo",
        "entity": "lots",
        "filters": {"product": "Nova-P1", "status": "Completed"},
        "records": [
            {
                "tenant_id": "demo",
                "lot_id": "DEMO-L000000000001",
                "product": "Nova-P1",
                "technology_nm": 28,
                "route": "LOGIC-18",
                "priority": "Normal",
                "start_time": "2026-10-24T00:00:00+00:00",
                "status": "Completed",
                "wafer_count": 25,
                "good_wafers": 24,
                "yield_rate": 0.96,
                "cycle_time_hours": 72.0,
                "synthetic": True,
            }
        ],
        "page": {
            "count": 1,
            "limit": 20,
            "position": 0,
            "estimated_total": 3,
            "next_cursor": "illustrative-opaque-next",
        },
    }


def _process_sample() -> dict[str, object]:
    return {
        "provider": "fake-enterprise-v1",
        "simulated": True,
        "tenant_id": "demo",
        "entity": "process-runs",
        "filters": {"equipment_id": "CMP-01", "process_step": "CMP"},
        "records": [
            {
                "tenant_id": "demo",
                "run_id": "RUN-000000000000001",
                "lot_id": "DEMO-L000000000001",
                "operation_seq": 1,
                "process_step": "CMP",
                "equipment_id": "CMP-01",
                "chamber": "CH-1",
                "recipe": "CMP-R01",
                "run_time": "2026-10-24T00:00:00+00:00",
                "measurement_name": "Normalized process metric",
                "measurement_value": 100.0,
                "measurement_unit": "a.u.",
                "pass_flag": 1,
                "synthetic": True,
            }
        ],
        "page": {
            "count": 1,
            "limit": 20,
            "position": 0,
            "estimated_total": 3,
            "next_cursor": "illustrative-opaque-next",
        },
    }


def _sensor_sample() -> dict[str, object]:
    return {
        "provider": "fake-enterprise-v1",
        "simulated": True,
        "tenant_id": "demo",
        "entity": "sensor-events",
        "filters": {
            "equipment_id": "CMP-01",
            "process_step": "CMP",
            "signal_name": "RF power",
        },
        "records": [
            {
                "tenant_id": "demo",
                "reading_id": "SNS-0000000000000001",
                "lot_id": "DEMO-L000000000001",
                "process_step": "CMP",
                "equipment_id": "CMP-01",
                "chamber": "CH-1",
                "sample_time": "2026-10-24T00:00:00+00:00",
                "signal_name": "RF power",
                "signal_value": 900.0,
                "signal_unit": "W",
                "is_missing": 0,
                "is_outlier": 0,
                "synthetic": True,
            }
        ],
        "page": {
            "count": 1,
            "limit": 20,
            "position": 0,
            "estimated_total": 3,
            "next_cursor": "illustrative-opaque-next",
        },
    }


def _scope(
    grain: str,
    start: str | None,
    end: str | None,
    *,
    process_steps: list[str] | None = None,
    equipment_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "tenant_id": "demo",
        "start": start,
        "end": end,
        "equipment_ids": equipment_ids or [],
        "process_steps": process_steps or [],
        "lot_ids": [],
        "grain": grain,
    }


class EnterpriseToolsRuntimeTests(unittest.TestCase):
    def run_demo(self, **overrides: object) -> dict[str, object]:
        return asyncio.run(demo._run(_args(**overrides)))

    def test_every_tool_adapter_and_execution_mode_has_full_explicit_output(
        self,
    ) -> None:
        cases = (
            (
                "get_enterprise_data_manifest",
                "{}",
                _manifest(),
                _scope("enterprise_manifest", None, None),
            ),
            (
                "get_enterprise_fab_summary",
                '{"process_step":"CMP","equipment_id":"CMP-01"}',
                _summary(),
                _scope(
                    "enterprise_aggregate",
                    "2026-07-27",
                    "2026-10-24",
                    process_steps=["CMP"],
                    equipment_ids=["CMP-01"],
                ),
            ),
            (
                "query_enterprise_data",
                '{"entity":"lots","product":"Nova-P1","status":"Completed"}',
                _lot_sample(),
                _scope("enterprise_sample", "2024-10-25", "2026-10-24"),
            ),
            (
                "query_enterprise_data",
                '{"entity":"process-runs","process_step":"CMP","equipment_id":"CMP-01"}',
                _process_sample(),
                _scope(
                    "enterprise_sample",
                    "2024-10-25",
                    "2026-10-24",
                    process_steps=["CMP"],
                    equipment_ids=["CMP-01"],
                ),
            ),
            (
                "query_enterprise_data",
                '{"entity":"sensor-events","process_step":"CMP","equipment_id":"CMP-01","signal_name":"RF power"}',
                _sensor_sample(),
                _scope(
                    "enterprise_sample",
                    "2024-10-25",
                    "2026-10-24",
                    process_steps=["CMP"],
                    equipment_ids=["CMP-01"],
                ),
            ),
        )
        for adapter in ("fake", "provider"):
            for mode in ("ready", "loop"):
                for tool, arguments, expected, expected_scope in cases:
                    with self.subTest(adapter=adapter, mode=mode, tool=tool):
                        payload = self.run_demo(
                            adapter=adapter, mode=mode, tool=tool, arguments=arguments
                        )
                        result = payload["typed_results"][0]
                        self.assertEqual(
                            (
                                result["tool"],
                                result["version"],
                                result["status"],
                                result["row_count"],
                            ),
                            (tool, "1.0.0", "succeeded", 1),
                        )
                        self.assertEqual(result["data"], expected)
                        source = next(iter(payload["sources"].values()))
                        self.assertEqual(
                            (
                                source["source_kind"],
                                source["scope"],
                            ),
                            ("fake", expected_scope),
                        )
                        self.assertEqual(result["error"], None)
                        self.assertEqual(result["state"], "completed")
                        self.assertEqual(
                            payload["observations"][0]["source_ref"], "TOOL:S01"
                        )
                        self.assertEqual(payload["observations"][0]["result"], expected)
                        if mode == "loop":
                            tool_message = payload["tool_messages"][0]
                            self.assertEqual(
                                tool_message["tool_call_id"], "enterprise-tool-1"
                            )
                            self.assertEqual(
                                json.loads(tool_message["content"])["data"], expected
                            )
                        self.assertEqual(payload["guard"]["per_tool_calls"], {tool: 1})
                        self.assertEqual(
                            payload["plan"]["steps"],
                            [{"step_id": "S01", "tool": tool, "depends_on": []}],
                        )
                        self.assertEqual(payload["plan"]["budget"]["max_tool_calls"], 1)
                        self.assertEqual(
                            payload["model_tool_selection_calls"],
                            0 if mode == "ready" else 1,
                        )
                        self.assertEqual(
                            payload["model_response_calls"], 0 if mode == "ready" else 2
                        )

    def test_every_sample_entity_retains_scoped_record_and_page_truth(self) -> None:
        cases = (
            ("lots", '{"product":"Nova-P1","status":"Completed"}', "start_time"),
            (
                "process-runs",
                '{"process_step":"CMP","equipment_id":"CMP-01"}',
                "run_time",
            ),
            (
                "sensor-events",
                '{"process_step":"CMP","equipment_id":"CMP-01","signal_name":"RF power"}',
                "sample_time",
            ),
        )
        for entity, arguments, timestamp in cases:
            with self.subTest(entity=entity):
                payload = self.run_demo(
                    tool="query_enterprise_data",
                    arguments='{"entity":"' + entity + '",' + arguments[1:],
                )
                data = payload["typed_results"][0]["data"]
                row = data["records"][0]
                self.assertEqual(data["entity"], entity)
                self.assertEqual(
                    (row["tenant_id"], row[timestamp], row["synthetic"]),
                    ("demo", "2026-10-24T00:00:00+00:00", True),
                )
                self.assertEqual(
                    data["page"],
                    {
                        "count": 1,
                        "limit": 20,
                        "position": 0,
                        "estimated_total": 3,
                        "next_cursor": "illustrative-opaque-next",
                    },
                )
                if entity == "lots":
                    self.assertEqual(row["product"], "Nova-P1")
                else:
                    self.assertEqual(
                        (row["process_step"], row["equipment_id"]), ("CMP", "CMP-01")
                    )
                self.assertEqual(
                    next(iter(payload["sources"].values()))["scope"]["start"],
                    "2024-10-25",
                )

    def test_default_windows_preserve_empty_original_filters(self) -> None:
        summary = self.run_demo(tool="get_enterprise_fab_summary", arguments="{}")
        self.assertEqual(summary["typed_results"][0]["data"]["query"]["filters"], {})
        self.assertEqual(
            next(iter(summary["sources"].values()))["scope"]["start"], "2026-07-27"
        )
        sample = self.run_demo(
            tool="query_enterprise_data", arguments='{"entity":"lots"}'
        )
        self.assertEqual(sample["typed_results"][0]["data"]["filters"], {})
        self.assertEqual(
            next(iter(sample["sources"].values()))["scope"]["start"], "2024-10-25"
        )

    def test_rejections_never_call_either_adapter_or_fixture_provider(self) -> None:
        invalid = (
            (
                "query_enterprise_data",
                '{"sql":"select 1"}',
                "invalid_arguments",
                "validation",
                {},
            ),
            (
                "query_enterprise_data",
                '{"entity":"lots","cursor":"x"}',
                "invalid_arguments",
                "validation",
                {},
            ),
            (
                "query_enterprise_data",
                '{"entity":"unknown"}',
                "invalid_arguments",
                "validation",
                {},
            ),
            (
                "query_enterprise_data",
                '{"entity":"lots","limit":true}',
                "invalid_arguments",
                "validation",
                {},
            ),
            (
                "query_enterprise_data",
                '{"entity":"lots","process_step":"CMP"}',
                "invalid_arguments",
                "validation",
                {},
            ),
            (
                "query_enterprise_data",
                '{"entity":[]}',
                "invalid_arguments",
                "validation",
                {},
            ),
            (
                "query_enterprise_data",
                '{"entity":"process-runs","process_step":"unknown"}',
                "invalid_arguments",
                "validation",
                {},
            ),
            ("query_manufacturing_data", "{}", "denied", "authorization", {}),
            (
                "get_enterprise_data_manifest",
                "{}",
                "denied",
                "authorization",
                {"role": "viewer"},
            ),
            (
                "get_enterprise_data_manifest",
                "{}",
                "denied",
                "authorization",
                {"tenant_id": "other"},
            ),
        )
        originals = {
            "fake": FakeEnterpriseToolsAdapter.fetch,
            "provider": ProviderEnterpriseToolsAdapter.fetch,
            "manifest": demo._FixtureProvider.manifest,
            "summary": demo._FixtureProvider.summary,
            "page": demo._FixtureProvider.page,
        }
        calls = {name: 0 for name in originals}

        def counted(name: str):
            def wrapper(*args: object, **kwargs: object):
                calls[name] += 1
                return originals[name](*args, **kwargs)

            return wrapper

        with (
            patch.object(FakeEnterpriseToolsAdapter, "fetch", counted("fake")),
            patch.object(ProviderEnterpriseToolsAdapter, "fetch", counted("provider")),
            patch.object(demo._FixtureProvider, "manifest", counted("manifest")),
            patch.object(demo._FixtureProvider, "summary", counted("summary")),
            patch.object(demo._FixtureProvider, "page", counted("page")),
        ):
            for adapter in ("fake", "provider"):
                for mode in ("ready", "loop"):
                    for tool, arguments, status, kind, overrides in invalid:
                        with self.subTest(
                            adapter=adapter, mode=mode, tool=tool, arguments=arguments
                        ):
                            for name in calls:
                                calls[name] = 0
                            payload = self.run_demo(
                                adapter=adapter,
                                mode=mode,
                                tool=tool,
                                arguments=arguments,
                                **overrides,
                            )
                            result = payload["typed_results"][0]
                            self.assertEqual(
                                (result["status"], result["error"]["kind"]),
                                (status, kind),
                            )
                            self.assertFalse(payload["sources"])
                            self.assertEqual(calls, {name: 0 for name in calls})

    def test_policy_denials_and_one_source_fault_have_no_fallback(self) -> None:
        for mode in ("ready", "loop"):
            calls = 0

            def failing(self: object, *args: object, **kwargs: object):
                nonlocal calls
                calls += 1
                raise EnterpriseDataError("fixture failure")

            with (
                self.subTest(mode=mode),
                patch.object(FakeEnterpriseToolsAdapter, "fetch", failing),
            ):
                payload = self.run_demo(mode=mode, tool="get_enterprise_data_manifest")
            result = payload["typed_results"][0]
            self.assertEqual(calls, 1)
            self.assertEqual(
                (result["status"], result["error"]["kind"]),
                ("failed", "data_source"),
            )
            self.assertFalse(payload["sources"])

        for mode in ("ready", "loop"):
            adapter_calls = 0
            provider_calls = 0
            fake_calls = 0
            original_provider_fetch = ProviderEnterpriseToolsAdapter.fetch
            original_fake_fetch = FakeEnterpriseToolsAdapter.fetch

            def counted_provider_adapter(
                self: object,
                *args: object,
                _fetch: object = original_provider_fetch,
                **kwargs: object,
            ):
                nonlocal adapter_calls
                adapter_calls += 1
                return _fetch(self, *args, **kwargs)  # type: ignore[operator]

            def failing_provider(self: object, *args: object, **kwargs: object):
                nonlocal provider_calls
                provider_calls += 1
                raise EnterpriseDataError("private provider secret")

            def counted_fake(
                self: object,
                *args: object,
                _fetch: object = original_fake_fetch,
                **kwargs: object,
            ):
                nonlocal fake_calls
                fake_calls += 1
                return _fetch(self, *args, **kwargs)  # type: ignore[operator]

            with (
                self.subTest(adapter="provider", mode=mode),
                patch.object(
                    ProviderEnterpriseToolsAdapter, "fetch", counted_provider_adapter
                ),
                patch.object(demo._FixtureProvider, "manifest", failing_provider),
                patch.object(FakeEnterpriseToolsAdapter, "fetch", counted_fake),
            ):
                payload = self.run_demo(
                    mode=mode,
                    adapter="provider",
                    tool="get_enterprise_data_manifest",
                )
            result = payload["typed_results"][0]
            self.assertEqual((adapter_calls, provider_calls, fake_calls), (1, 1, 0))
            self.assertEqual(
                (result["status"], result["error"]["kind"]),
                ("failed", "data_source"),
            )
            self.assertNotIn("private", result["error"]["public_message"])
            self.assertFalse(payload["sources"])

    def test_loop_fixture_refuses_missing_matching_tool_message(self) -> None:
        model = demo._LoopModel("get_enterprise_data_manifest", "{}")
        first = asyncio.run(model.complete(None, None))
        self.assertEqual(first.tool_calls[0].call_id, "enterprise-tool-1")
        with self.assertRaisesRegex(AssertionError, "tool message"):
            asyncio.run(model.complete(ModelRequest("second", ()), None))


if __name__ == "__main__":
    unittest.main()
