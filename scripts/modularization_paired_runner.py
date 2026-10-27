"""Parent coordinator for the isolated MOD-002 paired measurement protocol."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import select
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from difflib import unified_diff
from pathlib import Path, PurePosixPath
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCENES = ("ready_success", "loop_success", "knowledge_retrieval_success")
FIXTURE_CLOCK = {
    "capture_environment_date": "2026-10-22",
    "runtime_route_date": "2026-08-07",
    "scope": "input_patch_not_output_normalization",
}
MAX_LINE = 8 * 1024 * 1024
COMMAND_TIMEOUT = 120.0
STATIC_SUFFIXES = frozenset(
    {
        ".css",
        ".html",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".png",
        ".svg",
        ".webp",
        ".woff",
        ".woff2",
    }
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _safe_path(root: Path, relative: str) -> Path:
    part = PurePosixPath(relative)
    if (
        not relative
        or part.is_absolute()
        or "\\" in relative
        or ":" in relative
        or "." in part.parts
        or ".." in part.parts
    ):
        raise ValueError(f"unsafe archive member: {relative!r}")
    target = root.joinpath(*part.parts)
    if not _inside(root, target):
        raise ValueError(f"archive member escapes tree: {relative}")
    return target


def _copy_current_app(source: Path, target: Path) -> None:
    app = source / "app"
    if not app.is_dir() or app.is_symlink():
        raise ValueError("current app tree is missing or a symlink")
    for item in app.rglob("*"):
        relative = item.relative_to(source)
        if item.is_symlink():
            raise ValueError(f"symlink is not permitted: {relative}")
        if item.is_dir():
            continue
        if any(part in {".cache", "__pycache__", "cache"} for part in relative.parts):
            continue
        if not item.is_file() or (
            item.suffix != ".py"
            and not (
                "static" in relative.parts and item.suffix.lower() in STATIC_SUFFIXES
            )
        ):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, destination)


def create_trees(
    project: Path, temporary: Path, protocol: dict[str, Any]
) -> tuple[Path, Path, dict[str, Any]]:
    """Create reference/current trees; all fixtures deliberately come from the ZIP."""
    project = project.resolve(strict=True)
    builder = _load(
        "mod002_reference_builder",
        project / "scripts/build_modularization_reference.py",
    )
    metadata_path = project / protocol["reference_metadata"]
    archive_path = project / protocol["reference_zip"]
    if not _inside(project, metadata_path) or not _inside(project, archive_path):
        raise ValueError("protocol reference paths escape project")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("zip") != protocol["reference_zip"]:
        raise ValueError("reference metadata ZIP does not match protocol")
    builder.validate_archive(archive_path, metadata)
    reference = temporary / "reference"
    current = temporary / "current"
    reference.mkdir()
    current.mkdir()
    _copy_current_app(project, current)
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            target = _safe_path(reference, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            if info.filename.startswith("scripts/") or info.filename.startswith(
                "evaluations/"
            ):
                current_target = _safe_path(current, info.filename)
                current_target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, current_target.open("xb") as output:
                    shutil.copyfileobj(source, output)
    fixtures = {
        "scripts/modularization_baseline.py",
        "scripts/refactor_contracts.py",
        "scripts/evaluate_trace_replay.py",
        "evaluations/trace_replay_matrix.json",
    }
    if any(
        not (reference / member).is_file() or not (current / member).is_file()
        for member in fixtures
    ):
        raise ValueError("reference archive lacks a frozen fixture")
    return reference, current, metadata


class Child:
    """One isolated worker, with bounded line-oriented JSON IPC."""

    def __init__(
        self, tree: Path, runner_script: Path, timeout: float = COMMAND_TIMEOUT
    ):
        environment = {
            key: value
            for key, value in os.environ.items()
            if not (
                key.startswith(("FAB_", "DEEPSEEK_"))
                or key in {"PYTHONPATH", "DATABASE_URL", "DB_URL", "LOG_FILE"}
            )
        }
        environment["FAB_WORKSPACE_ENV_FILE"] = os.devnull
        environment["FAB_PROJECT_ENV_FILE"] = os.devnull
        self.stderr = tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(runner_script),
                    "--worker",
                    "--project-dir",
                    str(tree),
                ],
                cwd=tree,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr,
                env=environment,
            )
        except BaseException:
            self.stderr.close()
            raise
        assert self.process.stdin is not None and self.process.stdout is not None
        self.stdin, self.stdout, self.timeout, self.buffer = (
            self.process.stdin,
            self.process.stdout,
            timeout,
            b"",
        )

    def command(
        self, request: dict[str, Any], timeout: float | None = None
    ) -> dict[str, Any]:
        if self.process.poll() is not None:
            raise RuntimeError(f"worker exited with {self.process.returncode}")
        self.stdin.write((json.dumps(request, separators=(",", ":")) + "\n").encode())
        self.stdin.flush()
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        fd = self.stdout.fileno()
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                line, self.buffer = self.buffer[:newline], self.buffer[newline + 1 :]
                if len(line) > MAX_LINE:
                    raise RuntimeError("worker response exceeds maximum line length")
                try:
                    answer = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError("worker returned invalid JSON") from exc
                if not isinstance(answer, dict):
                    raise RuntimeError("worker response is not an object")
                return answer
            if len(self.buffer) > MAX_LINE:
                raise RuntimeError("worker response exceeds maximum line length")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("worker response deadline exceeded")
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                raise TimeoutError("worker response deadline exceeded")
            chunk = os.read(fd, min(65536, MAX_LINE + 1 - len(self.buffer)))
            if not chunk:
                raise RuntimeError(f"worker exited with {self.process.poll()}")
            self.buffer += chunk

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                try:
                    self.command({"command": "quit"}, 1.0)
                except (OSError, RuntimeError, TimeoutError, ValueError):
                    pass
                if self.process.poll() is None:
                    self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        finally:
            self.stdin.close()
            self.stdout.close()
            self.stderr.close()


def _origins(value: Any, tree: Path) -> dict[str, list[str]]:
    if not isinstance(value, dict) or not value:
        raise ValueError("worker did not provide origins")
    checked: dict[str, list[str]] = {}
    for module, paths in value.items():
        if not isinstance(module, str) or not isinstance(paths, list) or not paths:
            raise ValueError("invalid worker origins")
        if any(
            not isinstance(path, str) or not _inside(tree, Path(path)) for path in paths
        ):
            raise ValueError("worker import origin escapes isolated tree")
        checked[module] = paths
    return checked


def _fixture_clock(value: Any) -> dict[str, str]:
    if value != FIXTURE_CLOCK:
        raise ValueError("worker fixture clock does not match frozen inputs")
    return dict(value)


def _diff(expected: Any, actual: Any) -> str:
    if expected == actual:
        return ""
    return "".join(
        unified_diff(
            json.dumps(
                expected, ensure_ascii=False, indent=2, sort_keys=True
            ).splitlines(True),
            json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True).splitlines(
                True
            ),
            fromfile="baseline",
            tofile="worker",
        )
    )


def _offline_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or any(
        type(value.get(key)) is not int or value[key] != 0
        for key in ("network_calls", "database_calls")
    ):
        raise ValueError("worker offline policy is not zero-call")
    files = value.get("env_files")
    if not isinstance(files, dict) or files != {
        "workspace": os.devnull,
        "project": os.devnull,
    }:
        raise ValueError("worker offline policy has unsafe environment files")
    return value


def _stats(batches: list[list[int]]) -> dict[str, Any]:
    flat = [value for batch in batches for value in batch]
    p95 = sorted(flat)[(len(flat) * 95 + 99) // 100 - 1] if flat else None
    one = lambda values: {
        "median": int(statistics.median(values)),
        "p95": sorted(values)[(len(values) * 95 + 99) // 100 - 1],
        "min": min(values),
        "max": max(values),
    }
    return {
        "batches": [one(batch) for batch in batches],
        "pooled": one(flat)
        if flat
        else {"median": None, "p95": p95, "min": None, "max": None},
    }


def _empty_scene() -> dict[str, list[list[int]]]:
    return {
        key: []
        for key in (
            "wall_samples_ns",
            "thread_cpu_samples_ns",
            "process_cpu_samples_ns",
            "cleanup_samples_ns",
            "collected_objects",
            "first_run_ns",
            "warmups_ns",
            "prepare_cleanup_samples_ns",
            "prepare_collected_objects",
        )
    }


def _run(
    project: Path, observe: bool, samples: int | None, result: dict[str, Any]
) -> dict[str, Any]:
    paired = _load(
        "mod002_paired", project / "scripts/modularization_paired_baseline.py"
    )
    protocol = json.loads(
        (project / "evaluations/mod_002_paired_protocol_v1.json").read_text(
            encoding="utf-8"
        )
    )
    count = (
        samples
        if samples is not None
        else (2 if observe else protocol["sampling"]["formal_samples_per_batch"])
    )
    batches = 1 if observe else protocol["sampling"]["formal_batches"]
    if (
        type(count) is not int
        or count < (1 if observe else 100)
        or (not observe and count % 100)
    ):
        raise ValueError("formal samples must be >=100 and divisible by 100")
    mode = "observe" if observe else "formal"
    baseline_path = (project / protocol["behavior_baseline"]).resolve(strict=True)
    if not _inside(project, baseline_path):
        raise ValueError("behavior baseline escapes project")
    result.update(
        {
            "schema_version": "1.0",
            "mode": mode,
            "status": "failed",
            "protocol": protocol,
            "measurement": protocol.get("measurement"),
            "reference_metadata_status": "unknown",
            "reference_id": protocol.get("reference_id"),
            "behavior_diff": "",
            "behavior_baseline_diffs": {},
            "fixture_clocks": {},
            "reference_behavior_status": "failed",
            "current_behavior_status": "failed",
            "sampling": {
                "samples_per_batch": count,
                "batches": batches,
                "warmups_per_batch": 10,
                "block_size": 50,
            },
            "orders": [],
            "reference": {scene: _empty_scene() for scene in SCENES},
            "current": {scene: _empty_scene() for scene in SCENES},
        }
    )
    with tempfile.TemporaryDirectory(
        prefix="mod002-paired-", dir="/tmp" if os.name != "nt" else None
    ) as directory:
        reference_tree, current_tree, metadata = create_trees(
            project, Path(directory), protocol
        )
        result["isolated_trees"] = {
            "reference": str(reference_tree),
            "current": str(current_tree),
        }
        result["reference_metadata_status"] = metadata["status"]
        if not observe and metadata["status"] != "approved":
            raise ValueError("formal measurement requires approved reference")
        reference: Child | None = None
        current: Child | None = None
        try:
            reference = Child(
                reference_tree, project / "scripts/modularization_paired_baseline.py"
            )
            current = Child(
                current_tree, project / "scripts/modularization_paired_baseline.py"
            )
            ready_ref, ready_current = (
                reference.command({"command": "ready"}),
                current.command({"command": "ready"}),
            )
            result["environments"] = {
                "reference": ready_ref.get("environment"),
                "current": ready_current.get("environment"),
            }
            result["fixture_clocks"] = {
                "reference": _fixture_clock(ready_ref.get("fixture_clock")),
                "current": _fixture_clock(ready_current.get("fixture_clock")),
            }
            result["source_environment"] = {
                "workspace_env_file": os.devnull,
                "project_env_file": os.devnull,
            }
            result["offline_policy"] = {
                "reference": _offline_policy(ready_ref.get("offline_policy")),
                "current": _offline_policy(ready_current.get("offline_policy")),
            }
            result["origins"] = {
                "reference": _origins(ready_ref.get("origins"), reference_tree),
                "current": _origins(ready_current.get("origins"), current_tree),
            }
            expected_environment = getattr(paired, "ENVIRONMENT_KEYS", frozenset())
            environment = result["environments"]["reference"]
            if (
                not isinstance(environment, dict)
                or set(environment) != expected_environment
                or any(
                    not isinstance(value, str) or not value
                    for value in environment.values()
                )
                or environment != result["environments"]["current"]
            ):
                raise ValueError("reference/current environments differ")
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            ref_behavior, current_behavior = (
                reference.command({"command": "behavior"}),
                current.command({"command": "behavior"}),
            )
            _fixture_clock(ref_behavior.get("fixture_clock"))
            _fixture_clock(current_behavior.get("fixture_clock"))
            result["origins"] = {
                "reference": _origins(ref_behavior.get("origins"), reference_tree),
                "current": _origins(current_behavior.get("origins"), current_tree),
            }
            result["offline_policy"] = {
                "reference": _offline_policy(ref_behavior.get("offline_policy")),
                "current": _offline_policy(current_behavior.get("offline_policy")),
            }
            result["behavior_baseline_diffs"] = {
                "reference": _diff(baseline, ref_behavior.get("behavior")),
                "current": _diff(baseline, current_behavior.get("behavior")),
            }
            result["reference_behavior_status"] = (
                "passed"
                if not result["behavior_baseline_diffs"]["reference"]
                else "failed"
            )
            result["current_behavior_status"] = (
                "passed"
                if not result["behavior_baseline_diffs"]["current"]
                else "failed"
            )
            result["behavior_diff"] = _diff(
                ref_behavior.get("behavior"), current_behavior.get("behavior")
            )
            if (
                result["reference_behavior_status"] != "passed"
                or result["current_behavior_status"] != "passed"
                or result["behavior_diff"]
            ):
                raise ValueError("behavior baseline drift")
            block = count if observe else protocol["sampling"]["block_size"]
            for scene in SCENES:
                for batch in range(batches):
                    prepared = {
                        "reference": reference.command(
                            {"command": "prepare", "scene": scene}, 60.0
                        ),
                        "current": current.command(
                            {"command": "prepare", "scene": scene}, 60.0
                        ),
                    }
                    for side, answer in prepared.items():
                        _fixture_clock(answer.get("fixture_clock"))
                        result["offline_policy"][side] = _offline_policy(
                            answer.get("offline_policy")
                        )
                        result["origins"][side] = _origins(
                            answer.get("origins"),
                            reference_tree if side == "reference" else current_tree,
                        )
                        first = answer.get("first_run_ns")
                        warmups = answer.get("warmups_ns")
                        if (
                            not isinstance(first, list)
                            or len(first) != 1
                            or not all(paired._positive_int(value) for value in first)
                            or not isinstance(warmups, list)
                            or len(warmups) != 10
                            or not all(paired._positive_int(value) for value in warmups)
                        ):
                            raise ValueError(f"invalid {side} prepare response")
                        result[side][scene]["first_run_ns"].append(first)
                        result[side][scene]["warmups_ns"].append(warmups)
                        for key in ("cleanup_samples_ns", "collected_objects"):
                            diagnostic = answer.get(key)
                            if (
                                not isinstance(diagnostic, list)
                                or len(diagnostic) != 11
                                or not all(
                                    paired._nonnegative_int(value)
                                    for value in diagnostic
                                )
                            ):
                                raise ValueError(f"invalid {side} prepare {key}")
                            result[side][scene][f"prepare_{key}"].append(diagnostic)
                    for block_index, start in enumerate(range(0, count, block)):
                        sides = (
                            ["reference", "current"]
                            if (batch + block_index) % 2 == 0
                            else ["current", "reference"]
                        )
                        length = min(block, count - start)
                        result["orders"].append(
                            {
                                "scene": scene,
                                "batch": batch,
                                "block": block_index,
                                "sides": sides,
                                "count": length,
                            }
                        )
                        for side in sides:
                            answer = (
                                reference if side == "reference" else current
                            ).command(
                                {"command": "measure", "scene": scene, "count": length}
                            )
                            _fixture_clock(answer.get("fixture_clock"))
                            result["offline_policy"][side] = _offline_policy(
                                answer.get("offline_policy")
                            )
                            result["origins"][side] = _origins(
                                answer.get("origins"),
                                reference_tree if side == "reference" else current_tree,
                            )
                            for key in (
                                "wall_samples_ns",
                                "thread_cpu_samples_ns",
                                "process_cpu_samples_ns",
                                "cleanup_samples_ns",
                                "collected_objects",
                            ):
                                if (
                                    key not in answer
                                    or not isinstance(answer[key], list)
                                    or len(answer[key]) != length
                                    or not all(
                                        (
                                            paired._positive_int(value)
                                            if key == "wall_samples_ns"
                                            else paired._nonnegative_int(value)
                                        )
                                        for value in answer[key]
                                    )
                                ):
                                    raise ValueError(f"invalid {side} {key}")
                                if len(result[side][scene][key]) <= batch:
                                    result[side][scene][key].append([])
                                result[side][scene][key][batch].extend(answer[key])
                    print(
                        f"{scene}: batch {batch + 1}/{batches}, {count} samples per side",
                        file=sys.stderr,
                        flush=True,
                    )
            for side in ("reference", "current"):
                for scene in SCENES:
                    result[side][scene]["statistics"] = _stats(
                        result[side][scene]["wall_samples_ns"]
                    )
            if observe:
                result["status"] = "observed"
            else:
                result["comparison_diff"] = paired.compare_report(result, protocol)
                result["status"] = (
                    "passed" if not result["comparison_diff"] else "failed"
                )
        finally:
            try:
                if reference is not None:
                    reference.close()
            finally:
                if current is not None:
                    current.close()
    return result


def _reserve_report(path: Path) -> Any:
    if path.exists() or path.is_symlink():
        raise FileExistsError("report path already exists or is a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("x", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observe", action="store_true")
    parser.add_argument("--samples", type=int)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, default=PROJECT_DIR)
    args = parser.parse_args(argv)
    if args.report.is_symlink() or args.report.exists():
        raise FileExistsError("report path already exists or is a symlink")
    report = args.report.resolve(strict=False)
    stream = _reserve_report(report)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "mode": "observe" if args.observe else "formal",
        "status": "failed",
    }
    try:
        _run(args.project_dir.resolve(strict=True), args.observe, args.samples, payload)
    except Exception as exc:  # noqa: BLE001 - a failed run must still leave its report
        payload.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    with stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return 0 if payload.get("status") in {"passed", "observed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
