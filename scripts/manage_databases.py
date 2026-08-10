from __future__ import annotations

import argparse
import json
import sqlite3
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.database import (
    department_paths,
    migrate_legacy_database,
    validate_department_databases,
)
from app.department_schemas import SCHEMA_VERSION, TABLE_DEPARTMENTS


DEPARTMENT_NAMES = {"main": "manufacturing"}


def readonly_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def manifest() -> dict:
    paths = department_paths()
    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "departments": {},
    }
    for department, path in paths.items():
        tables = [name for name, owner in TABLE_DEPARTMENTS.items() if owner == department]
        connection = readonly_connection(path)
        try:
            counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
        result["departments"][DEPARTMENT_NAMES.get(department, department)] = {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "quick_check": quick_check,
            "tables": counts,
        }
    result["governance"] = validate_department_databases()
    return result


def backup(destination: Path) -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = destination / timestamp
    destination.mkdir(parents=True, exist_ok=True)
    if backup_dir.exists():
        raise FileExistsError(f"Backup destination already exists: {backup_dir}")
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{timestamp}.", dir=destination))
    try:
        for source in department_paths().values():
            source_connection = readonly_connection(source)
            try:
                target_connection = sqlite3.connect(staging_dir / source.name)
                try:
                    source_connection.backup(target_connection)
                finally:
                    target_connection.close()
            finally:
                source_connection.close()
        backup_manifest = manifest()
        (staging_dir / "manifest.json").write_text(
            json.dumps(backup_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        staging_dir.rename(backup_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return {"backup_dir": str(backup_dir), "manifest": backup_manifest}


def checkpoint() -> dict[str, tuple[int, int, int]]:
    result = {}
    for department, path in department_paths().items():
        connection = sqlite3.connect(path)
        try:
            result[department] = tuple(connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
        finally:
            connection.close()
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage department-owned Fab Insight databases")
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate_parser = subparsers.add_parser("migrate", help="Copy the legacy monolith into department databases")
    migrate_parser.add_argument("--force", action="store_true")
    subparsers.add_parser("check", help="Validate integrity, row counts, and cross-department contracts")
    backup_parser = subparsers.add_parser("backup", help="Create an online backup of all department databases")
    backup_parser.add_argument("--destination", type=Path, default=Path("backups/databases"))
    subparsers.add_parser("checkpoint", help="Checkpoint and truncate WAL files")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "migrate":
        output = {"migrated_rows": migrate_legacy_database(force=args.force), "manifest": manifest()}
    elif args.command == "backup":
        output = backup(args.destination)
    elif args.command == "checkpoint":
        output = checkpoint()
    else:
        output = manifest()
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
