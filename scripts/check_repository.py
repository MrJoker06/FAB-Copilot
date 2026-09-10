"""Run bounded repository hygiene and high-confidence static checks."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
STATIC_PATHS = ("app", "scripts", "tests")
RUFF_SELECT = "E9,F63,F7,F82"


def tracked_files(*, runner=subprocess.run) -> list[Path]:
    result = runner(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=PROJECT_DIR, check=True,
        capture_output=True,
    )
    return [PROJECT_DIR / item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def text_hygiene_errors(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        try:
            content = path.read_bytes()
            text = content.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if b"\0" in content:
            continue
        relative = path.relative_to(PROJECT_DIR)
        if b"\r" in content:
            errors.append(f"{relative}: use LF line endings")
        if text and not text.endswith("\n"):
            errors.append(f"{relative}: add a final newline")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip(" \t") != line:
                errors.append(f"{relative}:{line_number}: remove trailing whitespace")
    return errors


def check_hygiene(*, runner=subprocess.run) -> None:
    errors = text_hygiene_errors(tracked_files(runner=runner))
    if errors:
        raise RuntimeError("repository text hygiene failed:\n" + "\n".join(errors))


def run_static(*, runner=subprocess.run) -> None:
    runner([sys.executable, "-m", "compileall", "-q", *STATIC_PATHS], cwd=PROJECT_DIR, check=True)
    runner([sys.executable, "-m", "ruff", "check", "--select", RUFF_SELECT, *STATIC_PATHS], cwd=PROJECT_DIR, check=True)
    runner([sys.executable, "scripts/check_module_boundaries.py"], cwd=PROJECT_DIR, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hygiene-only", action="store_true")
    args = parser.parse_args(argv)
    check_hygiene()
    if not args.hygiene_only:
        run_static()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
