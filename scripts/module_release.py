"""Build a composable, source-only MOD-024 delivery cohort.

This deliberately is not a wheel builder.  The five archives are parts of one
source cohort and can only be installed together; their member lists are
derived from the MOD-003 ownership inventory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EVALUATION = ROOT / "evaluations" / "mod_024_release_v1.json"
BOUNDARIES = ROOT / "evaluations" / "mod_003_boundaries_v1.json"
TOOL_SOURCES = ROOT / "evaluations" / "mod_009_tool_sources_v1.json"
PORTABLE_UNITS = ROOT / "evaluations" / "portable_units_v1.json"
ARTIFACT_MANIFEST = "module-artifact.json"
RELEASE_MANIFEST = "module-release.json"
ASSET_ROOT = "app/skills/litho-cpk-diagnostic"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or str(path) != value
        or path.is_absolute()
        or ".." in path.parts
    ):
        raise ValueError(f"unsafe release path: {value!r}")
    return path


def _source_bytes(path: Path) -> bytes:
    if not path.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError(f"source escapes repository: {path}")
    data = path.read_bytes()
    if b"\r" in data or not data.endswith(b"\n"):
        raise ValueError(f"release source must be LF terminated: {path}")
    data.decode("utf-8")
    return data


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def load_spec(path: Path = EVALUATION) -> dict[str, Any]:
    spec = _json(path)
    if spec.get("schema_version") != 1 or not isinstance(spec.get("profiles"), dict):
        raise ValueError("MOD-024 specification is invalid")
    return spec


def ownership() -> tuple[dict[str, str], list[str]]:
    boundary = _json(BOUNDARIES)
    files = boundary.get("files")
    if boundary.get("schema_version") != 1 or not isinstance(files, list):
        raise ValueError("MOD-003 boundary inventory is invalid")
    result: dict[str, str] = {}
    groups: set[str] = set()
    for item in files:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not isinstance(item.get("artifact_group"), str)
        ):
            raise TypeError("MOD-003 ownership item is invalid")
        name, group = item["path"], item["artifact_group"]
        _safe(name)
        if not name.startswith("app/") or name in result or not (ROOT / name).is_file():
            raise ValueError(f"invalid MOD-003 managed member: {name}")
        result[name] = group
        groups.add(group)
    for relative in load_spec().get("skill_assets", []):
        if not isinstance(relative, str):
            raise TypeError("skill asset must be a path")
        _safe(relative)
        source = ROOT / ASSET_ROOT / relative
        member = f"{ASSET_ROOT}/{relative}"
        if not source.is_file() or member in result:
            raise ValueError(f"missing skill asset: {relative}")
        result[member] = "manufacturing_capability"
    return result, sorted(groups)


def profile_sources(spec: dict[str, Any] | None = None) -> dict[str, list[str]]:
    spec = spec or load_spec()
    tool = _json(TOOL_SOURCES).get("portable_source_files")
    portable = (
        _json(PORTABLE_UNITS).get("units", {}).get("model_transport", {}).get("files")
    )
    if not isinstance(tool, list) or not isinstance(portable, list):
        raise TypeError("source inventory is invalid")
    sources = {
        "tool_sources": tool,
        "skill_release": spec["profiles"]["skill_release"]["source_files"],
        "model_transport": [
            item
            for item in portable
            if isinstance(item, str) and item.startswith("app/")
        ],
    }
    owners, _ = ownership()
    for name, items in sources.items():
        if not isinstance(items, list) or not items or len(items) != len(set(items)):
            raise ValueError(f"profile {name} has duplicate or empty sources")
        for item in items:
            if not isinstance(item, str) or item not in owners:
                raise ValueError(f"unknown profile member for {name}: {item!r}")
    if sources["tool_sources"] != _json(TOOL_SOURCES)["portable_source_files"]:
        raise ValueError("tool_sources must exactly match MOD-009")
    resources = spec["profiles"]["skill_release"].get("resource_files", [])
    if not isinstance(resources, list) or len(resources) != len(set(resources)):
        raise ValueError("skill_release resources are invalid")
    for item in resources:
        if not isinstance(item, str) or item not in owners:
            raise ValueError(f"unknown skill resource: {item!r}")
    return sources


def _zip_write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def build(output: Path, *, build_id: str | None = None) -> dict[str, Any]:
    """Create deterministic archive parts and return/write their release manifest."""
    if not build_id:
        raise ValueError("an explicit build-id is required")
    spec = load_spec()
    owners, groups = ownership()
    sources = profile_sources(spec)
    output.mkdir(parents=True, exist_ok=True)
    cohort = spec["cohort"]
    version = spec["version"]
    archives: list[dict[str, Any]] = []
    for group in groups:
        members = sorted(name for name, owner in owners.items() if owner == group)
        filename = f"{group}-{version}.zip"
        metadata = {
            "schema_version": 1,
            "cohort": cohort,
            "version": version,
            "artifact": group,
            "members": members,
        }
        with zipfile.ZipFile(
            output / filename, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            _zip_write(
                archive,
                ARTIFACT_MANIFEST,
                (
                    json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n"
                ).encode(),
            )
            for member in members:
                if member.startswith(ASSET_ROOT + "/"):
                    source = ROOT / member
                else:
                    source = ROOT / member
                _zip_write(archive, member, _source_bytes(source))
        archives.append({"artifact": group, "filename": filename, "members": members})
    commit = _git_commit()
    selected = set().union(*map(set, sources.values()))
    selected.update(spec["profiles"]["skill_release"].get("resource_files", []))
    release = {
        "schema_version": 1,
        "cohort": cohort,
        "version": version,
        "source_commit": commit or None,
        "source_commit_status": "git" if commit else "unavailable",
        "build_id": build_id,
        "ownership": owners,
        "archives": archives,
        "profiles": {
            name: {
                "source_files": items,
                "resource_files": spec["profiles"][name].get("resource_files", []),
                "required_artifacts": groups,
                "external_dependencies": spec["profiles"][name][
                    "external_dependencies"
                ],
                "direct_dependencies": spec["profiles"][name].get(
                    "direct_dependencies", []
                ),
                "transitive_dependencies": spec["profiles"][name].get(
                    "transitive_dependencies", []
                ),
            }
            for name, items in sources.items()
        },
        "environment_locks": spec["environment_locks"],
        "deferred_app_files": sorted(set(owners) - selected),
    }
    (output / RELEASE_MANIFEST).write_text(
        json.dumps(release, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for script in ("install_module_release.py", "verify_module_release.py"):
        shutil.copyfile(ROOT / "scripts" / script, output / script)
    return release


def verify(output: Path) -> dict[str, Any]:
    # Share validation with the standalone installer so builder verification
    # cannot accept metadata or archive paths that installation would reject.
    from install_module_release import read

    metadata = _json(output / RELEASE_MANIFEST)
    release, members = read(output, list(metadata.get("profiles", {})))
    return {
        "cohort": release["cohort"],
        "archives": len(release["archives"]),
        "members": len(members),
    }
