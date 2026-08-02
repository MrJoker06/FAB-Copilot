"""Run the deterministic local quality gate without browser or model dependencies."""
from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable


PROJECT_DIR = Path(__file__).resolve().parent.parent
TEST_DIR = PROJECT_DIR / "tests"
RUNTIME_DIR = PROJECT_DIR / "runtime" / "quality"
# QA-001's last full audit confirmed this baseline.  Raise or lower it only after
# a deliberate full-audit decision, so accidental broad test deletion cannot pass.
MIN_PYTHON_TESTS = 175


def count_python_tests(test_dir: Path = TEST_DIR) -> int:
    """Count unittest-style methods without importing tests or mutating their fixtures."""
    total = 0
    for path in sorted(test_dir.glob("test_*.py")):
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
    paths = sorted(TEST_DIR.glob("test_*.py"))
    if not include_system:
        paths = [path for path in paths if path.name != "test_system.py"]
    return [f"tests.{path.stem}" for path in paths]


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
            [sys.executable, "-m", "coverage", "run", "--branch", "--source=app", "-m", "unittest", "discover", "-s", "tests"],
            [sys.executable, "-m", "coverage", "report", "--include", "app/*", "--fail-under=80"],
        ])
    if node_tests:
        commands.append(["node", "--test", *map(str, node_tests)])
    commands.extend([["node", "--check", str(path)] for path in static_scripts])
    commands.extend([
        [sys.executable, "scripts/evaluate_rag.py"],
        [sys.executable, "scripts/evaluate_playbooks.py"],
    ])
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
    run_commands(quality_commands(args.mode), environment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
