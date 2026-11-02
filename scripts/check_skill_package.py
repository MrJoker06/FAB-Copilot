"""Validate an explicit declarative Skill package without executing it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.skills import DependencyInventory, SkillPackage, SkillPackageError
from app.skills.manifest import parse_json_document


def load_inventory(path: Path) -> DependencyInventory:
    try:
        with path.open("rb") as handle:
            data = handle.read(128 * 1024 + 1)
        if len(data) > 128 * 1024:
            raise SkillPackageError("invalid_inventory", "inventory exceeds size limit")
        value = parse_json_document(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, SkillPackageError) as error:
        raise SkillPackageError(
            "invalid_inventory", "inventory is not readable JSON"
        ) from error
    required = {"schema_version", "kind", "tools", "workflows", "evidence_policies"}
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value["schema_version"] != "1.0.0"
        or value["kind"] != "skill_dependency_inventory"
    ):
        raise SkillPackageError(
            "invalid_inventory", "inventory has missing or unknown fields"
        )
    return DependencyInventory(
        value["tools"], value["workflows"], value["evidence_policies"]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--resource", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        package = SkillPackage.open(args.package, load_inventory(args.inventory))
        resources = package.read_resources(args.resource) if args.resource else ()
        print(
            json.dumps(
                {
                    "skill_id": package.manifest.skill_id,
                    "version": package.manifest.version,
                    "status": package.manifest.status,
                    "checked_dependencies": {
                        "tools": len(package.manifest.tools),
                        "workflow": package.manifest.workflow.component_id,
                        "evidence_policy": package.manifest.evidence_policy.component_id,
                    },
                    "declared_resources": [
                        resource.path for resource in package.manifest.resources
                    ],
                    "loaded_resources": [
                        {
                            "path": resource.path,
                            "size": len(resource.text.encode("utf-8")),
                        }
                        for resource in resources
                    ],
                    "execution_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except SkillPackageError as error:
        print(
            json.dumps(
                {"error_code": error.code, "message": error.message}, sort_keys=True
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
