"""CLI for building/verifying a MOD-024 source cohort."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from module_release import ROOT, build, verify


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "runtime" / "module-release"
    )
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if not args.verify:
        build(args.output, build_id=args.build_id)
    print(json.dumps(verify(args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
