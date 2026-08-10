from __future__ import annotations

import argparse
import fcntl
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RuntimeInstance:
    instance_id: str
    path: Path
    git_commit: str | None
    port: int | None
    modified_at: datetime
    size_bytes: int
    active: bool
    valid_manifest: bool

    def public_dict(self) -> dict:
        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["modified_at"] = self.modified_at.isoformat(timespec="seconds")
        return payload


def directory_size(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file() and not entry.is_symlink():
            try:
                total += entry.stat().st_size
            except FileNotFoundError:
                continue
    return total


def instance_active(path: Path) -> bool:
    lock_path = path / "service.lock"
    if not lock_path.is_file():
        return False
    try:
        with lock_path.open("r+") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            finally:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
    except OSError:
        return True
    return False


def remove_inactive_instance(path: Path) -> bool:
    lock_path = path / "service.lock"
    if not lock_path.is_file():
        return False
    try:
        with lock_path.open("r+") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            shutil.rmtree(path)
            return True
    except OSError:
        return False


def inspect_instance(path: Path) -> RuntimeInstance:
    manifest_path = path / "instance.json"
    manifest: dict = {}
    valid_manifest = False
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            valid_manifest = manifest.get("instance_id") == path.name
        except (OSError, json.JSONDecodeError):
            pass
    timestamp_path = manifest_path if manifest_path.exists() else path
    modified_at = datetime.fromtimestamp(timestamp_path.stat().st_mtime, timezone.utc)
    try:
        port = int(manifest["port"]) if manifest.get("port") is not None else None
    except (TypeError, ValueError):
        port = None
        valid_manifest = False
    return RuntimeInstance(
        instance_id=path.name,
        path=path,
        git_commit=str(manifest.get("git_commit") or "") or None,
        port=port,
        modified_at=modified_at,
        size_bytes=directory_size(path),
        active=instance_active(path),
        valid_manifest=valid_manifest,
    )


def discover_instances(root: Path) -> list[RuntimeInstance]:
    if not root.exists():
        return []
    return sorted(
        (inspect_instance(path) for path in root.iterdir() if path.is_dir() and not path.is_symlink()),
        key=lambda item: item.modified_at,
        reverse=True,
    )


def build_prune_plan(
    instances: list[RuntimeInstance],
    keep: int,
    older_than_days: int,
    protected_ids: set[str],
    now: datetime | None = None,
) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    valid_instances = [item for item in instances if item.valid_manifest]
    newest_ids = {item.instance_id for item in valid_instances[:keep]}
    plan = []
    for item in instances:
        reason = "eligible"
        action = "delete"
        if not item.valid_manifest:
            action, reason = "keep", "invalid_manifest"
        elif item.active:
            action, reason = "keep", "active"
        elif item.instance_id in protected_ids:
            action, reason = "keep", "explicitly_protected"
        elif item.instance_id in newest_ids:
            action, reason = "keep", "newest_retention"
        elif item.modified_at > cutoff:
            action, reason = "keep", "retention_period"
        plan.append({**item.public_dict(), "action": action, "reason": reason})
    return plan


def apply_prune_plan(root: Path, plan: list[dict]) -> list[str]:
    root = root.resolve()
    removed = []
    for item in plan:
        if item["action"] != "delete":
            continue
        candidate = Path(item["path"])
        if (
            candidate.name != item.get("instance_id")
            or candidate.is_symlink()
            or candidate.parent.resolve() != root
        ):
            raise RuntimeError(f"Refusing to delete path outside runtime root: {candidate}")
        path = candidate.resolve()
        if path.parent != root:
            raise RuntimeError(f"Refusing to delete path outside runtime root: {path}")
        try:
            current = inspect_instance(path)
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError(f"Refusing to delete unavailable runtime instance: {path}") from exc
        expected_snapshot = {
            "instance_id": item.get("instance_id"),
            "git_commit": item.get("git_commit"),
            "port": item.get("port"),
            "modified_at": item.get("modified_at"),
        }
        current_snapshot = {
            "instance_id": current.instance_id,
            "git_commit": current.git_commit,
            "port": current.port,
            "modified_at": current.modified_at.isoformat(timespec="seconds"),
        }
        if not current.valid_manifest or current.active or current_snapshot != expected_snapshot:
            raise RuntimeError(f"Refusing to delete changed or unsafe runtime instance: {path}")
        if remove_inactive_instance(path):
            removed.append(item["instance_id"])
    return removed


def summary(root: Path, plan: list[dict], applied: bool, removed: list[str] | None = None) -> dict:
    candidates = [item for item in plan if item["action"] == "delete"]
    return {
        "runtime_root": str(root.resolve()),
        "mode": "apply" if applied else "dry-run",
        "instances": len(plan),
        "active_instances": sum(1 for item in plan if item["active"]),
        "delete_candidates": len(candidates),
        "reclaimable_bytes": sum(item["size_bytes"] for item in candidates),
        "removed_instances": removed or [],
        "plan": plan,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect and prune isolated Fab runtime instances")
    parser.add_argument("--root", type=Path, default=PROJECT_DIR / "runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List runtime instances and lock state")
    prune_parser = subparsers.add_parser("prune", help="Build a retention plan; deletion requires --apply")
    prune_parser.add_argument("--keep", type=int, default=3)
    prune_parser.add_argument("--older-than-days", type=int, default=3)
    prune_parser.add_argument("--protect", action="append", default=[])
    prune_parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    instances = discover_instances(args.root)
    if args.command == "list":
        output = {
            "runtime_root": str(args.root.resolve()),
            "instances": len(instances),
            "total_bytes": sum(item.size_bytes for item in instances),
            "items": [item.public_dict() for item in instances],
        }
    else:
        if args.keep < 1 or args.older_than_days < 0:
            parser.error("--keep must be at least 1 and --older-than-days cannot be negative")
        plan = build_prune_plan(instances, args.keep, args.older_than_days, set(args.protect))
        removed = apply_prune_plan(args.root, plan) if args.apply else []
        output = summary(args.root, plan, args.apply, removed)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
