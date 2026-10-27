from __future__ import annotations

import asyncio
import copy
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "modularization_baseline.py"
)
SPEC = importlib.util.spec_from_file_location("modularization_baseline", MODULE_PATH)
baseline = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(baseline)


class ModularizationBaselineTests(unittest.TestCase):
    def test_behavior_has_required_real_runtime_scenarios_and_is_deterministic(self):
        first = baseline.collect_behavior()
        second = baseline.collect_behavior()
        self.assertEqual(first, second)
        self.assertEqual(
            set(first["scenarios"]),
            {
                "ready_success",
                "ready_dependency_failure",
                "loop_success",
                "loop_duplicate_blocked",
                "knowledge_retrieval_success",
                "knowledge_retrieval_empty_degraded",
            },
        )
        self.assertEqual(
            first["execution_policy"],
            {"network_calls": 0, "real_model_calls": 0, "database_calls": 0},
        )
        self.assertEqual(
            first["scenarios"]["loop_duplicate_blocked"]["loop_guard"]["blocked_calls"],
            2,
        )
        self.assertEqual(
            first["scenarios"]["loop_success"]["loop_guard"]["blocked_calls"], 0
        )
        self.assertTrue(
            any(
                item["status"] == "blocked"
                for item in first["scenarios"]["ready_dependency_failure"]["tool_trace"]
            )
        )
        success = first["scenarios"]["knowledge_retrieval_success"]
        empty = first["scenarios"]["knowledge_retrieval_empty_degraded"]
        self.assertEqual(success["input"]["question"], "解释一下化学机械抛光的基本原理")
        for scenario in (success, empty):
            self.assertEqual(scenario["model_request_count"], 1)
            self.assertEqual(scenario["intent_route"]["intent"], "general_knowledge")
            self.assertEqual(
                [
                    entry["arguments"]["source_types"]
                    for entry in scenario["tool_trace"]
                ],
                [["personal"], ["knowledge"]],
            )
        self.assertTrue(success["sources"])
        self.assertEqual(success["retrieval_decision"]["state"], "GROUND_FACTORY")
        self.assertFalse(success["knowledge_fallback"]["used"])
        self.assertTrue(empty["knowledge_fallback"]["used"])
        self.assertEqual(empty["retrieval_decision"]["state"], "MODEL_ONLY_FALLBACK")
        self.assertTrue(empty["knowledge_fallback"]["disclosure"])

    def test_default_behavior_baseline_detects_runtime_drift(self):
        expected = baseline.load_json(baseline.DEFAULT_BEHAVIOR)
        actual = baseline.collect_behavior()
        self.assertEqual(
            "", baseline.diff(expected, actual, baseline.DEFAULT_BEHAVIOR.name)
        )

    def test_normalization_only_removes_declared_volatile_fields(self):
        value = {
            "progress_events": [
                {
                    "run_id": "volatile",
                    "arguments": {"duration_ms": 9, "run_id": "business"},
                }
            ],
            "tool_trace": [
                {"duration_ms": 1, "events": {"plan": {"run_id": "business"}}}
            ],
            "evidence": {"run_id": "business"},
        }
        self.assertEqual(
            baseline.normalize(value),
            {
                "progress_events": [
                    {"arguments": {"duration_ms": 9, "run_id": "business"}}
                ],
                "tool_trace": [{"events": {"plan": {"run_id": "business"}}}],
                "evidence": {"run_id": "business"},
            },
        )

    def test_normalization_canonicalizes_only_system_answer_contract_objects(self):
        first = {
            "model_messages": [
                [
                    {
                        "role": "system",
                        "content": 'prefix\nanswer_contract={"z":2,"a":1}',
                    }
                ]
            ]
        }
        reordered = copy.deepcopy(first)
        reordered["model_messages"][0][0]["content"] = (
            'prefix\nanswer_contract={"a":1,"z":2}'
        )
        self.assertEqual(baseline.normalize(first), baseline.normalize(reordered))
        self.assertEqual(
            baseline.normalize(first)["model_messages"][0][0]["content"],
            'prefix\nanswer_contract={"a":1,"z":2}',
        )

    def test_normalization_preserves_noncanonicalizable_message_content(self):
        system_with_list = {
            "model_messages": [
                [
                    {
                        "role": "system",
                        "content": 'prefix\nanswer_contract={"items":[2,1]}',
                    }
                ]
            ]
        }
        reordered_list = copy.deepcopy(system_with_list)
        reordered_list["model_messages"][0][0]["content"] = (
            'prefix\nanswer_contract={"items":[1,2]}'
        )
        user_message = {
            "model_messages": [
                [
                    {
                        "role": "user",
                        "content": 'prefix\nanswer_contract={"z":2,"a":1}',
                    }
                ]
            ]
        }
        malformed = {
            "model_messages": [
                [
                    {
                        "role": "system",
                        "content": "prefix\nanswer_contract={not-json}",
                    }
                ]
            ]
        }
        self.assertNotEqual(
            baseline.normalize(system_with_list), baseline.normalize(reordered_list)
        )
        self.assertEqual(baseline.normalize(user_message), user_message)
        self.assertEqual(baseline.normalize(malformed), malformed)

    def test_behavior_diff_detects_business_drift(self):
        expected = baseline.collect_behavior()
        changed = copy.deepcopy(expected)
        changed["scenarios"]["ready_success"]["answer"] = "changed"
        self.assertIn("changed", baseline.diff(expected, changed, "behavior.json"))

    def test_same_length_message_drift_is_visible(self):
        expected = {"messages": [{"content": "ABCD"}]}
        actual = {"messages": [{"content": "WXYZ"}]}
        self.assertIn("WXYZ", baseline.diff(expected, actual, "behavior.json"))

    def test_nearest_rank_and_invalid_samples(self):
        self.assertEqual(baseline.percentile_nearest_rank([1, 2, 3, 4, 5], 95), 5)
        with self.assertRaises(ValueError):
            baseline.percentile_nearest_rank([], 95)

    def test_performance_environment_mismatch_never_passes(self):
        expected = self._performance("approved_gate", "A")
        actual = self._performance("approved_gate", "B")
        self.assertIn("incomparable", baseline.compare_performance(expected, actual))

    def _performance(self, status, environment="A"):
        scene = {
            "median_ns": 10,
            "p95_ns": 20,
            "samples_per_batch": 200,
            "batches": 2,
            "relative_allowance_pct": 15,
        }
        return {
            "schema_version": "1.3",
            "environment": {
                "python": environment,
                "implementation": "CPython",
                "os": "test-os",
                "machine": "test-machine",
                "node": "test-node",
                "httpx": "test-httpx",
                "proxy_environment": baseline.PROXY_ENVIRONMENT,
                "gc_policy": baseline.GC_POLICY,
            },
            "measurement": {
                "clock": "perf_counter_ns",
                "percentile": "nearest-rank",
                "status": status,
                "timed_region": "runtime",
                "proxy_environment": baseline.PROXY_ENVIRONMENT,
                "gc_policy": baseline.GC_POLICY,
                "formal_cli_default_sampling": "1000 samples per batch; 2 batches",
            },
            "scenarios": {name: dict(scene) for name in baseline.SCENES},
        }

    def test_observation_and_candidate_are_not_gates(self):
        actual = self._performance("candidate_calibration")
        for status in ("observation", "candidate_calibration"):
            self.assertIn(
                "not an approved frozen gate",
                baseline.compare_performance(self._performance(status), actual),
            )

    def test_approved_gate_compares_candidate_and_reports_regression(self):
        expected = self._performance("approved_gate")
        actual = self._performance("candidate_calibration")
        self.assertEqual("", baseline.compare_performance(expected, actual))

        regressed = copy.deepcopy(actual)
        regressed["scenarios"]["ready_success"]["median_ns"] = 12
        self.assertIn(
            "ready_success.median_ns: regression exceeds 15%",
            baseline.compare_performance(expected, regressed),
        )

    def test_invalid_performance_baseline_never_raises_key_error(self):
        self.assertIn("invalid", baseline.compare_performance({}, {}))

    def test_legacy_performance_schemas_are_rejected_against_gc_controlled_schema(
        self,
    ):
        for legacy_schema in ("1.1", "1.2"):
            with self.subTest(legacy_schema=legacy_schema):
                legacy = self._performance("approved_gate")
                legacy["schema_version"] = legacy_schema
                self.assertIn(
                    "unsupported performance schema",
                    baseline.compare_performance(
                        legacy, self._performance("approved_gate")
                    ),
                )

    def test_performance_schema_invalid_shapes_are_reported(self):
        valid = self._performance("approved_gate")
        cases = [
            (None, "payload is not an object"),
            ([], "payload is not an object"),
            ({**valid, "measurement": None}, "missing measurement metadata"),
            ({**valid, "measurement": []}, "missing measurement metadata"),
            ({**valid, "measurement": {}}, "invalid measurement.clock"),
            (
                {**valid, "measurement": {**valid["measurement"], "status": []}},
                "invalid measurement.status",
            ),
            (
                {**valid, "measurement": {**valid["measurement"], "status": {}}},
                "invalid measurement.status",
            ),
            ({**valid, "environment": None}, "missing environment"),
            ({**valid, "environment": []}, "missing environment"),
            (
                {**valid, "environment": {**valid["environment"], "node": ""}},
                "invalid environment",
            ),
            ({**valid, "scenarios": []}, "scenarios must be an object"),
            (
                {**valid, "scenarios": {**valid["scenarios"], "ready_success": []}},
                "invalid scenario ready_success",
            ),
            (
                {**valid, "scenarios": {**valid["scenarios"], "ready_success": None}},
                "invalid scenario ready_success",
            ),
            (
                {
                    **valid,
                    "scenarios": {
                        key: value
                        for key, value in valid["scenarios"].items()
                        if key != "loop_success"
                    },
                },
                "scenario set must exactly match required scenes",
            ),
        ]
        for payload, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                self.assertIn(
                    expected_error, baseline.compare_performance(payload, valid)
                )

    def test_performance_schema_invalid_numeric_values_are_reported(self):
        valid = self._performance("approved_gate")
        cases = [
            ("median_ns", float("nan"), "invalid ready_success.median_ns"),
            ("p95_ns", -1, "invalid ready_success.p95_ns"),
            (
                "relative_allowance_pct",
                float("nan"),
                "invalid ready_success.relative_allowance_pct",
            ),
            ("samples_per_batch", True, "invalid ready_success.samples_per_batch"),
            ("batches", 0, "invalid ready_success.batches"),
        ]
        for field, value, expected_error in cases:
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(valid)
                payload["scenarios"]["ready_success"][field] = value
                self.assertIn(
                    expected_error, baseline.compare_performance(payload, valid)
                )

    def test_approved_gate_requires_full_sampling_on_both_sides(self):
        valid = self._performance("approved_gate")
        for side in ("expected", "actual"):
            with self.subTest(side=side):
                expected, actual = copy.deepcopy(valid), copy.deepcopy(valid)
                target = expected if side == "expected" else actual
                target["scenarios"]["ready_success"]["samples_per_batch"] = 30
                target["scenarios"]["ready_success"]["batches"] = 1
                self.assertIn(
                    f"{side}.ready_success approved gate requires",
                    baseline.compare_performance(expected, actual),
                )

    def test_fixed_dates_and_knowledge_path_are_captured(self):
        ready = asyncio.run(baseline._capture_ready())
        knowledge = asyncio.run(baseline._capture_loop(duplicate=False, knowledge=True))
        self.assertIn("2026-08-01 至 2026-08-07", ready["question"])
        self.assertEqual(knowledge["question"], "解释一下化学机械抛光的基本原理")
        self.assertEqual(
            ready["result"]["intent_route"]["time_range"]["start"], "2026-08-01"
        )

    def test_fixture_guard_detects_network_and_database_from_runtime_handler(self):
        def network(**_kwargs):
            __import__("socket").create_connection(("example.invalid", 443))

        def database(**_kwargs):
            __import__("sqlite3").connect(":memory:")

        with self.assertRaisesRegex(AssertionError, "forbidden access"):
            asyncio.run(
                baseline._capture_ready(
                    handler_overrides={"get_process_capability": network}
                )
            )
        with self.assertRaisesRegex(AssertionError, "forbidden access"):
            asyncio.run(
                baseline._capture_ready(
                    handler_overrides={"get_process_capability": database}
                )
            )

    def test_fixture_guard_fails_closed_when_handler_swallows_network_error(self):
        def swallowing_network(**_kwargs):
            try:
                __import__("socket").create_connection(("example.invalid", 443))
            except AssertionError:
                pass
            return []

        with self.assertRaisesRegex(AssertionError, "forbidden access"):
            asyncio.run(
                baseline._capture_ready(
                    handler_overrides={"get_process_capability": swallowing_network}
                )
            )

    def test_fixture_proxy_environment_is_hidden_and_restored(self):
        observed_by_handler = []
        observed_by_model = []
        sentinels = {key: f"sentinel-{key}" for key in baseline.PROXY_ENV_KEYS}
        sentinels["MOD002_NON_PROXY_SENTINEL"] = "preserve-me"

        def snapshot():
            return {key: os.environ.get(key) for key in baseline.PROXY_ENV_KEYS}

        def handler(**kwargs):
            observed_by_handler.append(snapshot())
            return baseline._handler("get_process_capability")(**kwargs)

        def model_observer():
            observed_by_model.append(snapshot())
            self.assertEqual(os.environ["MOD002_NON_PROXY_SENTINEL"], "preserve-me")

        def network(**_kwargs):
            __import__("socket").create_connection(("example.invalid", 443))

        with patch.dict(os.environ, sentinels):
            asyncio.run(
                baseline._capture_ready(
                    handler_overrides={"get_process_capability": handler},
                    environment_observer=model_observer,
                )
            )
            self.assertTrue(observed_by_handler)
            self.assertTrue(observed_by_model)
            self.assertTrue(
                all(
                    value is None
                    for values in observed_by_handler + observed_by_model
                    for value in values.values()
                )
            )
            self.assertEqual(os.environ["HTTP_PROXY"], "sentinel-HTTP_PROXY")
            with self.assertRaisesRegex(AssertionError, "forbidden access"):
                asyncio.run(
                    baseline._capture_ready(
                        handler_overrides={"get_process_capability": network}
                    )
                )
            self.assertEqual(os.environ["HTTP_PROXY"], "sentinel-HTTP_PROXY")
            self.assertEqual(os.environ["MOD002_NON_PROXY_SENTINEL"], "preserve-me")

    def test_behavior_baseline_is_independent_of_host_proxy_settings(self):
        expected = baseline.load_json(baseline.DEFAULT_BEHAVIOR)
        sentinels = {key: f"sentinel-{key}" for key in baseline.PROXY_ENV_KEYS}
        with patch.dict(os.environ, sentinels):
            actual = baseline.collect_behavior()
        self.assertEqual(
            "", baseline.diff(expected, actual, baseline.DEFAULT_BEHAVIOR.name)
        )

    def test_capture_rejects_existing_targets_before_collecting(self):
        with tempfile.TemporaryDirectory() as directory:
            behavior = Path(directory) / "behavior.json"
            behavior.write_text("{}", encoding="utf-8")
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "baseline",
                        "--mode",
                        "capture",
                        "--behavior",
                        str(behavior),
                        "--skip-performance",
                    ],
                ),
                patch.object(
                    baseline,
                    "collect_behavior",
                    side_effect=AssertionError("must not collect"),
                ),
                self.assertRaises(FileExistsError),
            ):
                baseline.main()

    def test_main_uses_fixed_formal_cli_sampling_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            behavior = Path(directory) / "behavior.json"
            performance = Path(directory) / "performance.json"
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "baseline",
                        "--mode",
                        "capture",
                        "--behavior",
                        str(behavior),
                        "--performance",
                        str(performance),
                    ],
                ),
                patch.object(baseline, "collect_behavior", return_value={}),
                patch.object(
                    baseline, "collect_performance", return_value={}
                ) as collect,
            ):
                self.assertEqual(baseline.main(), 0)
            collect.assert_called_once_with(1000, 2)

    def test_bad_performance_sampling_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            baseline.collect_performance(samples=0, batches=1)

    def test_measure_uses_runtime_elapsed_and_ten_warmups(self):
        calls = []

        async def capture_ready(**_kwargs):
            self.assertEqual(calls[-1], "collect")
            calls.append("capture")
            return {"elapsed_runtime_ns": 777}

        def collect():
            calls.append("collect")
            return 3

        with (
            patch.object(
                baseline, "_capture_ready", new=AsyncMock(side_effect=capture_ready)
            ) as mocked,
            patch.object(baseline.gc, "collect", side_effect=collect) as cleanup,
        ):
            measurement = baseline._measure("ready_success", 2)
        self.assertEqual(mocked.await_count, 13)
        self.assertEqual(cleanup.call_count, 13)
        self.assertEqual(
            calls, [event for _ in range(13) for event in ("collect", "capture")]
        )
        self.assertEqual(measurement["first_run_ns"], 777)
        self.assertEqual(measurement["samples_ns"], [777, 777])
        self.assertEqual(len(measurement["cleanup_samples_ns"]), 13)
        self.assertEqual(measurement["collected_objects"], [3] * 13)

    def test_performance_collection_requires_preexisting_automatic_gc(self):
        with (
            patch.object(baseline.gc, "isenabled", return_value=False),
            patch.object(baseline.gc, "collect") as collect,
            patch.object(baseline.gc, "enable") as enable,
            patch.object(baseline.gc, "disable") as disable,
            self.assertRaisesRegex(RuntimeError, "automatic GC"),
        ):
            baseline.collect_performance()
        collect.assert_not_called()
        enable.assert_not_called()
        disable.assert_not_called()


if __name__ == "__main__":
    unittest.main()
