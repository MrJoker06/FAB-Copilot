"""Strict MOD-002 paired comparison core and isolated fixture worker."""

from __future__ import annotations

import argparse
import asyncio
import gc
import importlib.util
import json
import os
import statistics
import sys
import time as _stdlib_time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = PROJECT_DIR / "evaluations/mod_002_paired_protocol_v1.json"
SCENES = ("ready_success", "loop_success", "knowledge_retrieval_success")
ALLOWANCES = {
    "ready_success": 15.65,
    "loop_success": 16.36,
    "knowledge_retrieval_success": 15.64,
}
ENVIRONMENT_KEYS = frozenset(
    {
        "python",
        "implementation",
        "os",
        "machine",
        "node",
        "httpx",
        "gc_policy",
        "proxy_environment",
        "affinity",
    }
)
FIXTURE_CLOCK = {
    "capture_environment_date": "2026-10-22",
    "runtime_route_date": "2026-08-07",
    "scope": "input_patch_not_output_normalization",
}
_CLOCK = _stdlib_time.perf_counter_ns


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def percentile_nearest_rank(values: list[int], percentile: int = 95) -> int:
    if not values or percentile != 95:
        raise ValueError("only non-empty p95 nearest-rank samples are supported")
    return sorted(values)[(len(values) * percentile + 99) // 100 - 1]


def _positive_int(value: Any) -> bool:
    return type(value) is int and 0 < value < 2**63


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and 0 <= value < 2**63


def _same_batches(value: Any, batches: int, samples: int, check: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == batches
        and all(
            isinstance(batch, list)
            and len(batch) == samples
            and all(check(item) for item in batch)
            for batch in value
        )
    )


def _measurement_errors(
    side: str, scene: str, value: Any, batches: int, samples: int
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{side}.{scene}: missing scenario"]
    errors = []
    if not _same_batches(value.get("wall_samples_ns"), batches, samples, _positive_int):
        errors.append(f"{side}.{scene}: invalid wall_samples_ns")
    for key in (
        "thread_cpu_samples_ns",
        "process_cpu_samples_ns",
        "cleanup_samples_ns",
    ):
        if not _same_batches(value.get(key), batches, samples, _nonnegative_int):
            errors.append(f"{side}.{scene}: invalid {key}")
    if not _same_batches(
        value.get("collected_objects"), batches, samples, _nonnegative_int
    ):
        errors.append(f"{side}.{scene}: invalid collected_objects")
    if not _same_batches(value.get("first_run_ns"), batches, 1, _positive_int):
        errors.append(f"{side}.{scene}: invalid first_run_ns")
    if not _same_batches(value.get("warmups_ns"), batches, 10, _positive_int):
        errors.append(f"{side}.{scene}: invalid warmups_ns")
    for key in ("prepare_cleanup_samples_ns", "prepare_collected_objects"):
        if not _same_batches(value.get(key), batches, 11, _nonnegative_int):
            errors.append(f"{side}.{scene}: invalid {key}")
    return errors


def _provenance_error(report: dict[str, Any]) -> str:
    trees, origins, policies, clocks = (
        report.get(key)
        for key in (
            "isolated_trees",
            "origins",
            "offline_policy",
            "fixture_clocks",
        )
    )
    sides = {"reference", "current"}
    if any(
        not isinstance(value, dict) or set(value) != sides
        for value in (trees, origins, policies, clocks)
    ):
        return "missing isolated source or offline provenance"
    roots = {}
    for side in sides:
        if not isinstance(trees[side], str) or not Path(trees[side]).is_absolute():
            return "invalid isolated tree"
        roots[side] = Path(trees[side]).resolve()
        if not isinstance(origins[side], dict) or not origins[side]:
            return "missing module origins"
        for name, paths in origins[side].items():
            if not isinstance(name, str) or not (
                name in {"app", "scripts"} or name.startswith(("app.", "scripts."))
            ):
                return "invalid module origin name"
            if (
                not isinstance(paths, list)
                or not paths
                or any(
                    not isinstance(path, str)
                    or not Path(path).is_absolute()
                    or not Path(path).resolve().is_relative_to(roots[side])
                    for path in paths
                )
            ):
                return "mixed module origins"
        policy = policies[side]
        if not isinstance(policy, dict) or any(
            type(policy.get(key)) is not int or policy[key] != 0
            for key in ("network_calls", "database_calls")
        ):
            return "forbidden network or database access"
        if policy.get("env_files") != {"workspace": os.devnull, "project": os.devnull}:
            return "environment files are not disabled"
        if clocks[side] != FIXTURE_CLOCK:
            return "fixture clock does not match frozen inputs"
    if roots["reference"].is_relative_to(roots["current"]) or roots[
        "current"
    ].is_relative_to(roots["reference"]):
        return "reference and current trees overlap"
    return ""


def _order_errors(
    orders: Any, batches: int, samples: int, block_size: int
) -> list[str]:
    if not isinstance(orders, list) or samples % block_size:
        return ["invalid paired order"]
    blocks = samples // block_size
    expected_count = len(SCENES) * batches * blocks
    if len(orders) != expected_count:
        return ["paired order has missing or duplicate blocks"]
    errors: list[str] = []
    expected_entries = []
    for scene in SCENES:
        for batch in range(batches):
            for block in range(blocks):
                sides = (
                    ["reference", "current"]
                    if (batch + block) % 2 == 0
                    else ["current", "reference"]
                )
                expected_entries.append(
                    {
                        "scene": scene,
                        "batch": batch,
                        "block": block,
                        "sides": sides,
                        "count": block_size,
                    }
                )
    for entry, expected_entry in zip(orders, expected_entries):
        if (
            not isinstance(entry, dict)
            or set(entry) != set(expected_entry)
            or type(entry["batch"]) is not int
            or type(entry["block"]) is not int
            or type(entry["count"]) is not int
        ):
            errors.append("invalid paired order entry")
        elif entry != expected_entry:
            errors.append("paired order violates declared sequence")
    return errors


def compare_report(report: Any, protocol: Any) -> str:
    """Return empty only for a complete formal passing paired report."""
    if not isinstance(report, dict) or not isinstance(protocol, dict):
        return "invalid report or protocol"
    if (
        protocol.get("schema_version") != "1.0"
        or protocol.get("reference_id") != "mod-002-reference-v4"
    ):
        return "invalid protocol schema or reference id"
    protocol_sampling, expected = protocol.get("sampling"), protocol.get("scenarios")
    if (
        not isinstance(protocol_sampling, dict)
        or not isinstance(expected, dict)
        or set(expected) != set(SCENES)
    ):
        return "invalid protocol shape"
    minimum = protocol_sampling.get("minimum_samples_per_batch")
    if (
        not _positive_int(minimum)
        or minimum < 100
        or type(protocol_sampling.get("formal_batches")) is not int
        or protocol_sampling["formal_batches"] != 2
        or type(protocol_sampling.get("warmups_per_batch")) is not int
        or protocol_sampling["warmups_per_batch"] != 10
        or type(protocol_sampling.get("block_size")) is not int
        or protocol_sampling["block_size"] != 50
        or protocol_sampling.get("percentile") != "nearest-rank"
    ):
        return "invalid protocol sampling"
    declared = report.get("sampling")
    if not isinstance(declared, dict):
        return "missing declared sampling"
    samples, batches, warmups, block_size = (
        declared.get(key)
        for key in ("samples_per_batch", "batches", "warmups_per_batch", "block_size")
    )
    if (
        not _positive_int(samples)
        or samples < minimum
        or not _positive_int(batches)
        or batches != 2
        or type(warmups) is not int
        or warmups != 10
        or not _positive_int(block_size)
        or block_size != 50
        or samples % 100
        or samples % block_size
    ):
        return "invalid declared sampling"
    if (
        protocol_sampling.get("formal_batches") != batches
        or protocol_sampling.get("warmups_per_batch") != warmups
        or protocol_sampling.get("block_size") != block_size
    ):
        return "declared sampling differs from protocol"
    if any(
        not isinstance(expected.get(scene), dict)
        or expected[scene].get("relative_allowance_pct") != ALLOWANCES[scene]
        for scene in SCENES
    ):
        return "protocol allowances do not match v4"
    if report.get("schema_version") != "1.0":
        return "invalid report schema"
    if report.get("mode") != "formal":
        return "observation reports cannot pass the formal gate"
    if (
        report.get("reference_metadata_status") != "approved"
        or report.get("reference_id") != protocol["reference_id"]
    ):
        return "reference metadata is not approved"
    if (
        report.get("behavior_diff") != ""
        or report.get("reference_behavior_status") != "passed"
        or report.get("current_behavior_status") != "passed"
    ):
        return "behavior baseline drift"
    provenance_error = _provenance_error(report)
    if provenance_error:
        return provenance_error
    environments = report.get("environments")
    reference_environment = (
        environments.get("reference") if isinstance(environments, dict) else None
    )
    current_environment = (
        environments.get("current") if isinstance(environments, dict) else None
    )
    if (
        not isinstance(reference_environment, dict)
        or not isinstance(current_environment, dict)
        or set(reference_environment) != ENVIRONMENT_KEYS
        or reference_environment != current_environment
        or any(
            not isinstance(reference_environment[key], str)
            or not reference_environment[key]
            for key in ENVIRONMENT_KEYS
        )
    ):
        return "reference/current environments differ"
    sides = (report.get("reference"), report.get("current"))
    if not all(isinstance(side, dict) for side in sides) or any(
        set(side) != set(SCENES) for side in sides
    ):
        return "reference/current scenario sets differ"
    errors = _order_errors(report.get("orders"), batches, samples, block_size)
    for scene in SCENES:
        local = _measurement_errors(
            "reference", scene, sides[0].get(scene), batches, samples
        )
        local += _measurement_errors(
            "current", scene, sides[1].get(scene), batches, samples
        )
        errors.extend(local)
        if local:
            continue
        reference = [
            item for batch in sides[0][scene]["wall_samples_ns"] for item in batch
        ]
        current = [
            item for batch in sides[1][scene]["wall_samples_ns"] for item in batch
        ]
        for label, statistic in (
            ("median", lambda v: int(statistics.median(v))),
            ("p95", percentile_nearest_rank),
        ):
            if statistic(current) > statistic(reference) * (
                1 + ALLOWANCES[scene] / 100
            ):
                errors.append(
                    f"{scene}.{label}: exceeds fixed {ALLOWANCES[scene]}% allowance"
                )
    return "\n".join(errors)


def _sanitize_environment() -> None:
    for key in tuple(os.environ):
        upper = key.upper()
        if upper.startswith(
            (
                "FAB_",
                "DEEPSEEK_",
                "AGENT_LOG_",
                "DB_",
                "DATABASE_",
                "POSTGRES_",
                "MYSQL_",
                "SQLITE_",
            )
        ) or upper in {"API_TIMEOUT_MS", "PYTHONPATH", "DATABASE_URL"}:
            os.environ.pop(key, None)
    os.environ["FAB_WORKSPACE_ENV_FILE"] = os.devnull
    os.environ["FAB_PROJECT_ENV_FILE"] = os.devnull


def _origins(project_dir: Path) -> dict[str, list[str]]:
    root, output = project_dir.resolve(), {}
    for name, loaded in list(sys.modules.items()):
        if (
            name != "app"
            and name != "scripts"
            and not name.startswith(("app.", "scripts."))
        ):
            continue
        paths = []
        if getattr(loaded, "__file__", None):
            paths.append(str(Path(loaded.__file__).resolve()))
        if getattr(loaded, "__path__", None) is not None:
            paths.extend(str(Path(item).resolve()) for item in loaded.__path__)
        paths = sorted(set(paths))
        if not paths or any(not Path(item).is_relative_to(root) for item in paths):
            raise RuntimeError(f"mixed import origin: {name}")
        output[name] = paths
    return output


def _worker_module(project_dir: Path):
    project_dir, script = (
        project_dir.resolve(),
        project_dir.resolve() / "scripts" / "modularization_baseline.py",
    )
    if not script.is_file():
        raise RuntimeError("missing frozen fixture")
    sys.path[:] = [str(project_dir)] + [
        item for item in sys.path if item and Path(item).resolve() != project_dir
    ]
    spec = importlib.util.spec_from_file_location("paired_fixture", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _origins(project_dir)
    return module


def _fixture_clock_control():
    """Load the harness clock control without importing fixture-side scripts."""
    script = Path(__file__).with_name("modularization_fixture_clock.py")
    spec = importlib.util.spec_from_file_location(
        "mod002_fixture_clock_control", script
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load fixture clock control")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _worker_environment() -> dict[str, str]:
    import platform

    import httpx

    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "node": platform.node(),
        "httpx": httpx.__version__,
        "gc_policy": "collect_before_each_fixture_sample_auto_gc_enabled",
        "proxy_environment": "excluded_inside_offline_fixture",
        "affinity": json.dumps(
            sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else [],
            separators=(",", ":"),
        ),
    }


class _AccessGuard:
    def __init__(self) -> None:
        self.network_calls = self.database_calls = 0

    def network(self, *args: Any, **kwargs: Any) -> None:
        self.network_calls += 1
        raise AssertionError("MOD-002 worker attempted network access")

    def database(self, *args: Any, **kwargs: Any) -> None:
        self.database_calls += 1
        raise AssertionError("MOD-002 worker attempted database access")

    def assert_clean(self) -> None:
        if self.network_calls or self.database_calls:
            raise AssertionError(
                f"MOD-002 worker forbidden access: network_calls={self.network_calls}, database_calls={self.database_calls}"
            )


def _offline_policy(guard: _AccessGuard) -> dict[str, Any]:
    return {
        "network_calls": guard.network_calls,
        "database_calls": guard.database_calls,
        "env_files": {
            "workspace": os.environ["FAB_WORKSPACE_ENV_FILE"],
            "project": os.environ["FAB_PROJECT_ENV_FILE"],
        },
    }


def worker_main(project_dir: Path) -> int:
    if not gc.isenabled():
        raise RuntimeError("automatic GC must be enabled")
    _sanitize_environment()
    guard = _AccessGuard()
    with ExitStack() as stack:
        stack.enter_context(patch("socket.socket.connect", new=guard.network))
        stack.enter_context(patch("socket.socket.connect_ex", new=guard.network))
        stack.enter_context(patch("sqlite3.connect", new=guard.database))
        module = _worker_module(project_dir)
        clock_control = _fixture_clock_control()
        fixture_clock_metadata = dict(clock_control.FIXTURE_CLOCK)
        stack.enter_context(clock_control.fixed_capture_clock())
        # Keep the fixture's timing surface isolated: its two calls remain the wall-clock calls.
        timing_calls = 0
        timing_stamps: list[tuple[int, int]] = []

        def fixture_clock() -> int:
            nonlocal timing_calls
            timing_calls += 1
            timing_stamps.append(
                (_stdlib_time.thread_time_ns(), _stdlib_time.process_time_ns())
            )
            return _CLOCK()

        module.time = SimpleNamespace(perf_counter_ns=fixture_clock)
        captures = {
            "ready_success": module._capture_ready,
            "loop_success": lambda: module._capture_loop(duplicate=False),
            "knowledge_retrieval_success": lambda: module._capture_loop(
                duplicate=False, knowledge=True
            ),
        }
        held_behavior: Any = None

        def run(scene: str) -> tuple[int, int, int, int, int]:
            nonlocal timing_calls, timing_stamps
            cleanup_start = _CLOCK()
            collected = gc.collect()
            cleanup = _CLOCK() - cleanup_start
            timing_calls = 0
            timing_stamps = []
            capture = asyncio.run(captures[scene]())
            if timing_calls != 2:
                raise AssertionError(
                    f"fixture timing contract requires exactly two calls, got {timing_calls}"
                )
            thread_cpu = timing_stamps[1][0] - timing_stamps[0][0]
            process_cpu = timing_stamps[1][1] - timing_stamps[0][1]
            return (
                int(capture["elapsed_runtime_ns"]),
                thread_cpu,
                process_cpu,
                cleanup,
                collected,
            )

        for line in sys.stdin:
            command = json.loads(line)
            kind = command.get("command") if isinstance(command, dict) else None
            if kind == "ready":
                answer = {
                    "environment": _worker_environment(),
                    "origins": _origins(project_dir),
                    "offline_policy": _offline_policy(guard),
                    "fixture_clock": fixture_clock_metadata,
                }
            elif kind == "behavior":
                held_behavior = module.collect_behavior()
                answer = {
                    "behavior": held_behavior,
                    "origins": _origins(project_dir),
                    "offline_policy": _offline_policy(guard),
                    "fixture_clock": fixture_clock_metadata,
                }
            elif kind == "prepare":
                scene = command.get("scene")
                if scene not in captures:
                    raise RuntimeError("invalid prepare command")
                first, warmups = run(scene), [run(scene) for _ in range(10)]
                answer = {
                    "first_run_ns": [first[0]],
                    "warmups_ns": [item[0] for item in warmups],
                    "cleanup_samples_ns": [first[3]] + [item[3] for item in warmups],
                    "collected_objects": [first[4]] + [item[4] for item in warmups],
                    "origins": _origins(project_dir),
                    "offline_policy": _offline_policy(guard),
                    "fixture_clock": fixture_clock_metadata,
                }
            elif kind == "measure":
                scene, count = command.get("scene"), command.get("count")
                if scene not in captures or type(count) is not int or count < 1:
                    raise RuntimeError("invalid measure command")
                values = [run(scene) for _ in range(count)]
                answer = {
                    "wall_samples_ns": [v[0] for v in values],
                    "thread_cpu_samples_ns": [v[1] for v in values],
                    "process_cpu_samples_ns": [v[2] for v in values],
                    "cleanup_samples_ns": [v[3] for v in values],
                    "collected_objects": [v[4] for v in values],
                    "origins": _origins(project_dir),
                    "offline_policy": _offline_policy(guard),
                    "fixture_clock": fixture_clock_metadata,
                }
            elif kind == "quit":
                print(json.dumps({"quit": True}), flush=True)
                return 0
            else:
                raise RuntimeError("unknown worker command")
            guard.assert_clean()
            print(json.dumps(answer), flush=True)
    return 0


def main() -> int:
    if "--worker" not in sys.argv[1:]:
        spec = importlib.util.spec_from_file_location(
            "modularization_paired_runner",
            PROJECT_DIR / "scripts" / "modularization_paired_runner.py",
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("missing paired runner")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.main(sys.argv[1:])
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--project-dir", type=Path)
    args = parser.parse_args()
    if args.project_dir is None:
        raise SystemExit("--worker requires --project-dir")
    return worker_main(args.project_dir)


if __name__ == "__main__":
    raise SystemExit(main())
