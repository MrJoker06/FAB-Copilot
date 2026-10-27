from __future__ import annotations

import copy
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "paired", PROJECT_DIR / "scripts/modularization_paired_baseline.py"
)
paired = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(paired)


def formal_report(value: int = 100) -> dict:
    samples, batches, block = 100, 2, 50
    runs = [[value] * samples for _ in range(batches)]
    metric = {
        "wall_samples_ns": copy.deepcopy(runs),
        "thread_cpu_samples_ns": copy.deepcopy(runs),
        "process_cpu_samples_ns": copy.deepcopy(runs),
        "cleanup_samples_ns": copy.deepcopy(runs),
        "collected_objects": [[0] * samples for _ in range(batches)],
        "first_run_ns": [[value] for _ in range(batches)],
        "warmups_ns": [[value] * 10 for _ in range(batches)],
        "prepare_cleanup_samples_ns": [[value] * 11 for _ in range(batches)],
        "prepare_collected_objects": [[0] * 11 for _ in range(batches)],
    }
    orders = []
    for scene in paired.SCENES:
        for batch in range(batches):
            for item in range(samples // block):
                sides = (
                    ["reference", "current"]
                    if (batch + item) % 2 == 0
                    else ["current", "reference"]
                )
                orders.append(
                    {
                        "scene": scene,
                        "batch": batch,
                        "block": item,
                        "sides": sides,
                        "count": block,
                    }
                )
    return {
        "schema_version": "1.0",
        "mode": "formal",
        "sampling": {
            "samples_per_batch": samples,
            "batches": batches,
            "warmups_per_batch": 10,
            "block_size": block,
        },
        "orders": orders,
        "reference_metadata_status": "approved",
        "reference_id": "mod-002-reference-v4",
        "behavior_diff": "",
        "reference_behavior_status": "passed",
        "current_behavior_status": "passed",
        "isolated_trees": {
            side: f"/tmp/mod002-test/{side}" for side in ("reference", "current")
        },
        "origins": {
            side: {"app": [f"/tmp/mod002-test/{side}/app/__init__.py"]}
            for side in ("reference", "current")
        },
        "offline_policy": {
            side: {
                "network_calls": 0,
                "database_calls": 0,
                "env_files": {"workspace": os.devnull, "project": os.devnull},
            }
            for side in ("reference", "current")
        },
        "fixture_clocks": {
            side: dict(paired.FIXTURE_CLOCK) for side in ("reference", "current")
        },
        "environments": {
            "reference": {key: "set" for key in paired.ENVIRONMENT_KEYS},
            "current": {key: "set" for key in paired.ENVIRONMENT_KEYS},
        },
        "reference": {scene: copy.deepcopy(metric) for scene in paired.SCENES},
        "current": {scene: copy.deepcopy(metric) for scene in paired.SCENES},
    }


class PairedComparisonTests(unittest.TestCase):
    def setUp(self):
        self.protocol = paired.load_json(paired.PROTOCOL_PATH)

    def test_equal_formal_report_passes(self):
        self.assertEqual("", paired.compare_report(formal_report(), self.protocol))

    def test_none_protocol_bool_inf_and_three_batches_fail_closed(self):
        self.assertTrue(paired.compare_report(formal_report(), None))
        for mutate in (
            lambda x: x["sampling"].update(batches=True),
            lambda x: x["sampling"].update(samples_per_batch=float("inf")),
            lambda x: x["sampling"].update(batches=3),
        ):
            report = formal_report()
            mutate(report)
            self.assertTrue(paired.compare_report(report, self.protocol))

    def test_invalid_protocol_sampling_and_reference_id_fail_closed(self):
        cases = []
        for key, value in (
            ("minimum_samples_per_batch", True),
            ("formal_batches", True),
            ("warmups_per_batch", True),
            ("block_size", 50.0),
        ):
            protocol = copy.deepcopy(self.protocol)
            protocol["sampling"][key] = value
            cases.append(protocol)
        protocol = copy.deepcopy(self.protocol)
        protocol["reference_id"] = "other"
        cases.append(protocol)
        for protocol in cases:
            self.assertTrue(paired.compare_report(formal_report(), protocol))

    def test_declared_counts_orders_and_warmups_are_required(self):
        cases = []
        report = formal_report()
        report["sampling"]["samples_per_batch"] = 101
        cases.append(report)
        report = formal_report()
        report["orders"] = report["orders"][:-1]
        cases.append(report)
        report = formal_report()
        report["orders"][0]["sides"] = ["current", "reference"]
        cases.append(report)
        report = formal_report()
        report["reference"]["ready_success"]["warmups_ns"][0] = [1]
        cases.append(report)
        report = formal_report()
        report["current"]["ready_success"]["thread_cpu_samples_ns"][0][0] = float("nan")
        cases.append(report)
        report = formal_report()
        report["reference"]["ready_success"]["first_run_ns"][0] = 1
        cases.append(report)
        report = formal_report()
        report["schema_version"] = None
        cases.append(report)
        for report in cases:
            self.assertTrue(paired.compare_report(report, self.protocol))

    def test_cpu_is_diagnostic_and_not_a_performance_gate(self):
        report = formal_report()
        report["current"]["ready_success"]["thread_cpu_samples_ns"][0] = [100000] * 100
        report["current"]["ready_success"]["process_cpu_samples_ns"][0] = [0] * 100
        self.assertEqual("", paired.compare_report(report, self.protocol))

    def test_malformed_scenario_and_source_provenance_fail_closed(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["scenarios"]["ready_success"] = None
        self.assertTrue(paired.compare_report(formal_report(), protocol))
        for mutate in (
            lambda report: report.pop("origins"),
            lambda report: report["origins"]["current"].update(app=["/outside/app.py"]),
            lambda report: report["isolated_trees"].update(
                current=report["isolated_trees"]["reference"]
            ),
            lambda report: report["offline_policy"]["current"].update(
                network_calls=False
            ),
            lambda report: report["offline_policy"]["current"]["env_files"].update(
                project=".env"
            ),
            lambda report: report.pop("fixture_clocks"),
            lambda report: report["fixture_clocks"]["current"].update(
                runtime_route_date="2099-01-01"
            ),
            lambda report: report["current"]["ready_success"]["wall_samples_ns"][
                0
            ].__setitem__(0, 2**1024),
        ):
            report = formal_report()
            mutate(report)
            self.assertTrue(paired.compare_report(report, self.protocol))

    def test_observation_behavior_and_fixed_p95_cannot_pass(self):
        report = formal_report()
        report["mode"] = "observe"
        self.assertTrue(paired.compare_report(report, self.protocol))
        report = formal_report()
        report["behavior_diff"] = "changed"
        self.assertTrue(paired.compare_report(report, self.protocol))
        report = formal_report()
        report["current"]["loop_success"]["wall_samples_ns"][0][-11:] = [1000] * 11
        self.assertIn("loop_success.p95", paired.compare_report(report, self.protocol))

    def test_orders_must_be_in_complete_declared_sequence(self):
        report = formal_report()
        report["orders"][0], report["orders"][1] = (
            report["orders"][1],
            report["orders"][0],
        )
        self.assertTrue(paired.compare_report(report, self.protocol))
        report = formal_report()
        report["orders"][0]["count"] = 50.0
        self.assertTrue(paired.compare_report(report, self.protocol))

    def test_main_forwards_non_worker_cli_and_returns_runner_status(self):
        runner_main = Mock(return_value=17)
        loader = SimpleNamespace(exec_module=Mock())
        spec = SimpleNamespace(loader=loader)
        module = SimpleNamespace(main=runner_main)
        with (
            patch.object(sys, "argv", ["paired", "--observe", "--samples", "30"]),
            patch.object(
                paired.importlib.util, "spec_from_file_location", return_value=spec
            ),
            patch.object(
                paired.importlib.util, "module_from_spec", return_value=module
            ),
        ):
            self.assertEqual(17, paired.main())
        runner_main.assert_called_once_with(["--observe", "--samples", "30"])
