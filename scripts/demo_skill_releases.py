"""Demonstrate explicit immutable Skill publication without executing a Skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.skills.contracts import SkillPackageError
from app.skills.releases import SkillReleaseStore
from scripts.check_skill_package import load_inventory


def _release(value: object) -> dict[str, object]:
    from app.skills.releases import PublishedSkill

    assert isinstance(value, PublishedSkill)
    return {
        "skill_id": value.reference.skill_id,
        "version": value.reference.version,
        "resources": [
            {
                "path": item.path,
                "kind": item.kind,
                "size": len(item.text.encode("utf-8")),
            }
            for item in value.resources
        ],
    }


def _states(store: SkillReleaseStore) -> list[dict[str, object]]:
    return [
        {
            "skill_id": item.reference.skill_id,
            "version": item.reference.version,
            "enabled": item.enabled,
            "active": item.active,
        }
        for item in store.states()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--upgrade-package", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--resource", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        inventory = load_inventory(args.inventory)
        store = SkillReleaseStore()
        first = store.publish(args.package, inventory)
        second = store.publish(args.upgrade_package, inventory)
        if first.reference.skill_id != second.reference.skill_id:
            raise SkillPackageError(
                "invalid_selection", "upgrade package must use the same skill id"
            )
        store.activate(first.reference)
        old_loader = store.loader(first.reference, inventory)
        old_snapshot = old_loader.load(first.reference)
        store.activate(second.reference)
        resources = tuple(args.resource) or ("references/release.md",)
        old_expanded = old_loader.expand(old_snapshot, resources)
        errors: list[str] = []
        try:
            store.publish(args.package, inventory)
        except SkillPackageError as error:
            errors.append(error.code)
        store.disable(second.reference)
        try:
            store.require_enabled(second.reference)
        except SkillPackageError as error:
            errors.append(error.code)
        rollback = store.rollback(first.reference)
        print(
            json.dumps(
                {
                    "execution_authorized": False,
                    "published": [_release(first), _release(second)],
                    "rollback_target": {
                        "skill_id": rollback.reference.skill_id,
                        "version": rollback.reference.version,
                    },
                    "states": _states(store),
                    "pinned_old_content_unchanged": old_snapshot.loaded_resources[
                        0
                    ].text
                    == old_expanded.loaded_resources[0].text,
                    "old_loaded_paths": [
                        item.path for item in old_expanded.loaded_resources
                    ],
                    "expected_error_codes": errors,
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
