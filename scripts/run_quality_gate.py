"""Run the deterministic local quality gate; full includes isolated browser coverage."""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


PROJECT_DIR = Path(__file__).resolve().parent.parent
TEST_DIR = PROJECT_DIR / "tests"
RUNTIME_DIR = PROJECT_DIR / "runtime" / "quality"
# QA-001's last full audit confirmed this baseline.  Raise or lower it only after
# a deliberate full-audit decision, so accidental broad test deletion cannot pass.
MIN_PYTHON_TESTS = 175
SYSTEM_TEST_PACKAGE = "tests.system"
SYSTEM_TEST_BUDGETS_PATH = PROJECT_DIR / "evaluations" / "system_test_budgets.json"
SYSTEM_TIMINGS_PATH = RUNTIME_DIR / "system_test_timings.json"


def count_python_tests(test_dir: Path = TEST_DIR) -> int:
    """Count unittest-style methods without importing tests or mutating their fixtures."""
    total = 0
    for path in sorted(test_dir.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        total += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            for method in node.body
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith("test")
        )
    return total


def python_test_modules(include_system: bool) -> list[str]:
    paths = sorted(TEST_DIR.rglob("test_*.py"))
    if not include_system:
        paths = [path for path in paths if SYSTEM_TEST_PACKAGE not in module_name_for_path(path)]
    return [module_name_for_path(path) for path in paths]


def module_name_for_path(path: Path, test_dir: Path = TEST_DIR) -> str:
    """Return the importable module name for a test path below ``tests``."""
    return ".".join((test_dir.name, *path.relative_to(test_dir).with_suffix("").parts))


def system_test_modules() -> list[str]:
    return [
        module_name_for_path(path)
        for path in sorted(TEST_DIR.joinpath("system").glob("test_*.py"))
    ]


def load_system_test_budgets(path: Path = SYSTEM_TEST_BUDGETS_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_system_test_budgets(budgets: dict[str, object], modules: list[str]) -> None:
    """Reject stale or unsafe runtime-budget configuration before starting tests."""
    if budgets.get("schema_version") != 1:
        raise ValueError("system test budget schema_version must be 1")
    configured = budgets.get("modules")
    total = budgets.get("total")
    if not isinstance(configured, dict) or set(configured) != set(modules):
        raise ValueError("system test budget modules must exactly match discovered modules")
    for name, budget in [*configured.items(), ("total", total)]:
        if not isinstance(budget, dict):
            raise ValueError(f"system test budget {name} must be an object")
        warning = budget.get("warning_seconds")
        failure = budget.get("fail_seconds")
        if not isinstance(warning, (int, float)) or not isinstance(failure, (int, float)) or not 0 < warning < failure:
            raise ValueError(f"system test budget {name} requires 0 < warning_seconds < fail_seconds")


def _budget_status(seconds: float, budget: dict[str, float]) -> str:
    if seconds > budget["fail_seconds"]:
        return "failed"
    if seconds >= budget["warning_seconds"]:
        return "warning"
    return "passed"


def run_system_tests(environment: dict[str, str], *, runner=subprocess.run, clock=time.monotonic) -> None:
    """Run isolated system modules serially and retain timing diagnostics on failure."""
    budgets = load_system_test_budgets()
    modules = system_test_modules()
    validate_system_test_budgets(budgets, modules)
    configured = budgets["modules"]
    results: list[dict[str, object]] = []
    started = clock()
    failure: BaseException | None = None
    try:
        for module in modules:
            budget = configured[module]
            command = [sys.executable, "-m", "coverage", "run", "--append", "--branch", "--source=app", "-m", "unittest", module]
            print("+", " ".join(command), flush=True)
            module_started = clock()
            test_status = "passed"
            error_details: dict[str, object] = {}
            try:
                runner(command, cwd=PROJECT_DIR, env=environment, check=True)
            except BaseException as error:
                test_status = "failed"
                error_details = {
                    "error_type": type(error).__name__,
                    "returncode": getattr(error, "returncode", None),
                }
                failure = error
            finally:
                seconds = clock() - module_started
                budget_status = _budget_status(seconds, budget)
                status = "failed" if test_status == "failed" else budget_status
                results.append({
                    "module": module, "seconds": seconds, **budget,
                    "test_status": test_status, "budget_status": budget_status, "status": status,
                    **error_details,
                })
                if budget_status == "warning":
                    print(f"WARNING system test {module}: {seconds:.1f}s (warning at {budget['warning_seconds']:.1f}s)", flush=True)
            if failure is not None:
                raise failure
            if budget_status == "failed":
                failure = RuntimeError(f"system test budget exceeded for {module}: {seconds:.1f}s > {budget['fail_seconds']:.1f}s")
                raise failure
    finally:
        total_seconds = clock() - started
        total_budget = budgets["total"]
        total_budget_status = _budget_status(total_seconds, total_budget)
        total_test_status = "failed" if failure is not None else "passed"
        total_status = "failed" if total_test_status == "failed" else total_budget_status
        report = {
            "schema_version": budgets["schema_version"],
            "modules": results,
            "total": {
                "seconds": total_seconds, **total_budget, "test_status": total_test_status,
                "budget_status": total_budget_status, "status": total_status,
            },
        }
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        SYSTEM_TIMINGS_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if total_budget_status == "warning":
            print(f"WARNING system tests total: {total_seconds:.1f}s (warning at {total_budget['warning_seconds']:.1f}s)", flush=True)
        if total_budget_status == "failed" and failure is None:
            raise RuntimeError(f"system test total budget exceeded: {total_seconds:.1f}s > {total_budget['fail_seconds']:.1f}s")


def quality_commands(mode: str) -> list[list[str]]:
    if mode not in {"quick", "full"}:
        raise ValueError(f"unsupported quality gate mode: {mode}")
    node_tests = sorted(TEST_DIR.glob("*.test.js"))
    static_scripts = sorted((PROJECT_DIR / "app" / "static").glob("*.js"))
    commands: list[list[str]] = []
    if mode == "quick":
        commands.append([sys.executable, "-m", "unittest", *python_test_modules(include_system=False)])
    else:
        commands.extend([
            [sys.executable, "-m", "coverage", "erase"],
            [sys.executable, "-m", "coverage", "run", "--branch", "--source=app", "-m", "unittest", *python_test_modules(include_system=False)],
        ])
    if node_tests:
        commands.append(["node", "--test", *map(str, node_tests)])
    commands.extend([["node", "--check", str(path)] for path in static_scripts])
    commands.extend([
        [sys.executable, "scripts/evaluate_rag.py"],
        [sys.executable, "scripts/evaluate_ocr.py"],
        [sys.executable, "scripts/evaluate_playbooks.py"],
    ])
    if mode == "full":
        commands.append(["npm", "run", "test:e2e"])
        commands.append([sys.executable, "-m", "coverage", "report", "--include", "app/*", "--fail-under=80"])
    return commands


def run_commands(commands: Iterable[list[str]], environment: dict[str, str] | None = None) -> None:
    for command in commands:
        print("+", " ".join(command), flush=True)
        subprocess.run(command, cwd=PROJECT_DIR, env=environment, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("quick", "full"))
    args = parser.parse_args(argv)
    test_count = count_python_tests()
    if test_count < MIN_PYTHON_TESTS:
        raise SystemExit(f"quality gate rejected {test_count} Python tests; expected at least {MIN_PYTHON_TESTS}")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["COVERAGE_FILE"] = str(RUNTIME_DIR / ".coverage")
    print(f"discovered {test_count} Python tests", flush=True)
    commands = quality_commands(args.mode)
    if args.mode == "full":
        coverage_report = commands.pop(-1)
        run_commands(commands[:2], environment)
        run_system_tests(environment)
        run_commands([coverage_report, *commands[2:]], environment)
    else:
        run_commands(commands, environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
