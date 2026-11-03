"""Inspect explicit Skill packages without discovering from the host or executing them."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.skills.catalog import SkillCatalog, SkillReference
from app.skills.contracts import SkillPackageError
from app.skills.discovery import DiscoveryQuery, discover
from app.skills.loader import SkillLoader
from scripts.check_skill_package import load_inventory


def _entry(entry: object) -> dict[str, object]:
    from app.skills.catalog import CatalogEntry

    assert isinstance(entry, CatalogEntry)
    return {
        "skill_id": entry.reference.skill_id,
        "version": entry.reference.version,
        "available": entry.available,
        "unavailable_reason": entry.unavailable_reason,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="append", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--workflow")
    parser.add_argument("--process-step")
    parser.add_argument("--mode", choices=("ready", "loop"))
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--skill-id")
    parser.add_argument("--version")
    parser.add_argument("--resource", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if bool(args.skill_id) != bool(args.version):
            raise SkillPackageError(
                "invalid_selection",
                "skill id and exact version must be supplied together",
            )
        if args.resource and not args.skill_id:
            raise SkillPackageError(
                "invalid_selection",
                "resource loading requires an exact skill selection",
            )
        catalog = SkillCatalog.build(args.package, load_inventory(args.inventory))
        result = discover(
            catalog,
            DiscoveryQuery(
                args.workflow, args.process_step, args.mode, frozenset(args.input)
            ),
        )
        output: dict[str, object] = {
            "candidates": [_entry(item) for item in result.candidates],
            "rejections": [
                {
                    "skill_id": item.reference.skill_id,
                    "version": item.reference.version,
                    "reason": item.reason,
                }
                for item in result.rejections
            ],
            "loaded_resources": [],
            "stages": ["metadata"],
            "execution_authorized": False,
        }
        if args.skill_id:
            reference = SkillReference(args.skill_id, args.version)
            selected_entry = catalog.find(reference)
            if not selected_entry.available:
                raise SkillPackageError(
                    selected_entry.unavailable_reason or "unavailable_skill",
                    "selected skill is unavailable",
                )
            if reference not in tuple(item.reference for item in result.candidates):
                raise SkillPackageError(
                    "selection_no_match",
                    "selected skill does not match the discovery query",
                )
            loader = SkillLoader(catalog)
            snapshot = loader.load(reference)
            output["stages"] = ["metadata", "instructions"]
            if args.resource:
                snapshot = loader.expand(snapshot, args.resource)
                output["stages"].append("explicit_resources")  # type: ignore[union-attr]
            output["selected"] = {
                "skill_id": reference.skill_id,
                "version": reference.version,
                "workflow": snapshot.manifest.workflow.component_id,
                "workflow_version": snapshot.manifest.workflow.version,
                "evidence_policy": snapshot.manifest.evidence_policy.component_id,
                "evidence_policy_version": snapshot.manifest.evidence_policy.version,
            }
            output["loaded_resources"] = [
                {
                    "path": item.path,
                    "kind": item.kind,
                    "size": len(item.text.encode("utf-8")),
                }
                for item in snapshot.loaded_resources
            ]
        print(json.dumps(output, sort_keys=True))
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
