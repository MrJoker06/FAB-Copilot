"""Freeze the reviewed MOD-002 reference tree without copying a worktree."""

from __future__ import annotations

import argparse
import json
import stat
import subprocess
import zipfile
from collections.abc import Callable
from datetime import date
from pathlib import Path, PurePosixPath

PROJECT_DIR = Path(__file__).resolve().parent.parent
REFERENCE_ID = "mod-002-reference-v4"
BASE_REVISION = "0c93cf6075e181caf1e61dfbcc6c616ff3a0f7e4"
OVERLAYS = (
    "app/core/identity.py",
    "app/core/settings.py",
    "app/core/identity_contracts.py",
    "app/manufacturing/enterprise_data.py",
    "app/manufacturing/data_contracts.py",
    "app/knowledge/rag.py",
    "app/knowledge/ranking.py",
    "app/knowledge/search_contracts.py",
    "app/knowledge/search_query.py",
    "app/knowledge/search_registry.py",
    "app/knowledge/sqlite_backend.py",
)
FIXTURES = (
    "scripts/modularization_baseline.py",
    "scripts/refactor_contracts.py",
    "scripts/evaluate_trace_replay.py",
    "evaluations/trace_replay_matrix.json",
)
REJECTED_SUFFIXES = {
    ".env",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".xlsx",
    ".pyc",
    ".pem",
    ".key",
    ".jsonl",
}
BEHAVIOR_BASELINE = "evaluations/mod_002_behavior_baseline_v2.json"
APPROVAL_FIELDS = {
    "source_audit": "passed",
    "behavior_baseline": BEHAVIOR_BASELINE,
}


def _safe_member(name: str) -> PurePosixPath:
    """Return a canonical, explicitly approved reference member path."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"unsafe reference member: {name!r}")
    path = PurePosixPath(name)
    if (
        name != path.as_posix()
        or path.is_absolute()
        or "\\" in name
        or ":" in name
        or ".." in path.parts
        or "." in path.parts
        or any(part in {".env", ".cache", "__pycache__"} for part in path.parts)
        or (not name.startswith("app/") and name not in FIXTURES)
        or path.suffix in REJECTED_SUFFIXES
    ):
        raise ValueError(f"unsafe reference member: {name}")
    return path


def _safe_relative_path(path: str) -> PurePosixPath:
    if not isinstance(path, str) or not path:
        raise ValueError("metadata ZIP path must be a relative POSIX path")
    candidate = PurePosixPath(path)
    if (
        path != candidate.as_posix()
        or candidate.is_absolute()
        or "\\" in path
        or ":" in path
        or ".." in candidate.parts
        or "." in candidate.parts
    ):
        raise ValueError("metadata ZIP path must be a relative POSIX path")
    return candidate


def _inside_project(project: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(project.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _git(project: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=project, check=True, capture_output=True
    ).stdout


def base_members(project: Path, git: Callable[..., bytes] = _git) -> tuple[str, ...]:
    rows = git(project, "ls-tree", "-r", BASE_REVISION).decode().splitlines()
    selected = []
    for row in rows:
        mode, kind, _, name = row.split(None, 3)
        _safe_relative_path(name)
        if name.startswith("app/"):
            _safe_member(name)
            if mode != "100644" or kind != "blob":
                raise ValueError(f"reference base contains non-regular member: {name}")
            selected.append(name)
    return tuple(sorted(str(_safe_member(name)) for name in selected))


def validate_archive(archive_path: Path, metadata: dict) -> None:
    required_keys = {
        "schema_version",
        "reference_id",
        "base_revision",
        "zip",
        "status",
        "members",
    }
    if not isinstance(metadata, dict) or not metadata:
        raise ValueError("invalid reference metadata schema")
    status = metadata.get("status")
    expected_keys = required_keys | ({"approval"} if status == "approved" else set())
    if set(metadata) != expected_keys:
        raise ValueError("invalid reference metadata schema")
    if (
        metadata["schema_version"] != "1.0"
        or metadata["reference_id"] != REFERENCE_ID
        or metadata["base_revision"] != BASE_REVISION
        or not isinstance(status, str)
        or status not in {"frozen_reference_candidate", "approved"}
    ):
        raise ValueError("invalid reference metadata identity")
    if status == "approved":
        approval = metadata["approval"]
        if not isinstance(approval, dict) or not approval:
            raise ValueError("approved reference requires approval metadata")
        if any(approval.get(name) != value for name, value in APPROVAL_FIELDS.items()):
            raise ValueError("invalid reference approval metadata")
        reviewed_on = approval.get("reviewed_on")
        try:
            if (
                not isinstance(reviewed_on, str)
                or date.fromisoformat(reviewed_on).isoformat() != reviewed_on
            ):
                raise ValueError
        except ValueError:
            raise ValueError("invalid reference approval metadata") from None
        _safe_relative_path(approval.get("behavior_report"))
    _safe_relative_path(metadata["zip"])
    entries = metadata["members"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("reference metadata members must be a non-empty list")
    expected: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "source"}:
            raise ValueError("invalid reference metadata member")
        name, source = entry["path"], entry["source"]
        safe = str(_safe_member(name))
        expected_source = (
            "current-reviewed-overlay"
            if safe in OVERLAYS
            else "current-fixture"
            if safe in FIXTURES
            else f"git:{BASE_REVISION}"
        )
        if source != expected_source or safe in expected:
            raise ValueError(f"invalid reference metadata member: {name}")
        expected.add(safe)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != expected:
                raise ValueError("archive members do not exactly match metadata")
            for info in infos:
                _safe_member(info.filename)
                mode = info.external_attr >> 16
                if (
                    info.is_dir()
                    or stat.S_IFMT(mode) != stat.S_IFREG
                    or stat.S_IMODE(mode) != 0o644
                ):
                    raise ValueError(f"unsafe archive mode: {info.filename}")
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid reference archive") from exc


def build_members(
    project: Path, git: Callable[..., bytes] = _git
) -> dict[str, tuple[str, bytes]]:
    members: dict[str, tuple[str, bytes]] = {}
    for name in base_members(project, git):
        members[name] = (
            f"git:{BASE_REVISION}",
            git(project, "show", f"{BASE_REVISION}:{name}"),
        )
    for name in OVERLAYS + FIXTURES:
        safe = str(_safe_member(name))
        source = project / safe
        if (
            source.is_symlink()
            or not _inside_project(project, source)
            or not source.is_file()
        ):
            raise ValueError(f"missing or unsafe overlay/fixture: {safe}")
        members[safe] = (
            "current-reviewed-overlay" if safe in OVERLAYS else "current-fixture",
            source.read_bytes(),
        )
    for name in members:
        _safe_member(name)
    if "app/evidence/serialization.py" in members:
        raise ValueError("reference must not include optimized serialization helper")
    return members


def write_reference(
    project: Path, output_zip: Path, metadata: Path, git: Callable[..., bytes] = _git
) -> None:
    resolved_zip = output_zip.resolve(strict=False)
    resolved_metadata = metadata.resolve(strict=False)
    if resolved_zip == resolved_metadata:
        raise ValueError("reference ZIP and metadata targets must differ")
    if (
        output_zip.exists()
        or output_zip.is_symlink()
        or metadata.exists()
        or metadata.is_symlink()
    ):
        raise FileExistsError(
            "reference ZIP or metadata already exists; refusing overwrite"
        )
    if not output_zip.parent.is_dir() or not metadata.parent.is_dir():
        raise FileNotFoundError("reference output parents must already exist")
    if not _inside_project(project, output_zip) or not _inside_project(
        project, metadata
    ):
        raise ValueError("reference outputs must remain within the project")
    project_resolved = project.resolve(strict=True)
    zip_name = resolved_zip.relative_to(project_resolved).as_posix()
    _safe_relative_path(zip_name)
    zip_created = False
    metadata_created = False
    try:
        members = build_members(project, git)
        with zipfile.ZipFile(resolved_zip, "x", zipfile.ZIP_DEFLATED) as archive:
            zip_created = True
            for name, (_, content) in sorted(members.items()):
                info = zipfile.ZipInfo(name, (2026, 10, 22, 0, 0, 0))
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, content)
        payload = {
            "schema_version": "1.0",
            "reference_id": REFERENCE_ID,
            "base_revision": BASE_REVISION,
            "zip": zip_name,
            "status": "frozen_reference_candidate",
            "members": [
                {"path": name, "source": source}
                for name, (source, _) in sorted(members.items())
            ],
        }
        with resolved_metadata.open("x", encoding="utf-8") as metadata_file:
            metadata_created = True
            metadata_file.write(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
        validate_archive(resolved_zip, payload)
    except Exception:
        if metadata_created:
            resolved_metadata.unlink(missing_ok=True)
        if zip_created:
            resolved_zip.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--zip", type=Path, default=PROJECT_DIR / "evaluations/mod_002_reference_v4.zip"
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=PROJECT_DIR / "evaluations/mod_002_reference_v4.json",
    )
    args = parser.parse_args()
    write_reference(PROJECT_DIR, args.zip, args.metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
