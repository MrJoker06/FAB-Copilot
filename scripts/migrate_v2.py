from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATABASE_OWNERS = {
    "manufacturing_operations.db": "mcp",
    "equipment_engineering.db": "mcp",
    "yield_quality.db": "mcp",
    "process_knowledge.db": "api",
    "ai_operations.db": "api",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def database_manifest(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables
        }
        migration_table = "schema_migrations" in tables
        schema_version = (
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            if migration_table
            else None
        )
    finally:
        connection.close()
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "quick_check": quick_check,
        "schema_version": schema_version,
        "tables": counts,
    }


def backup_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    target_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def storage_manifest(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"files": 0, "size_bytes": 0, "sha256": {}}
    files = sorted(path for path in root.rglob("*") if path.is_file())
    return {
        "files": len(files),
        "size_bytes": sum(path.stat().st_size for path in files),
        "sha256": {str(path.relative_to(root)): file_sha256(path) for path in files},
    }


def preflight(source_dir: Path, personal_source: Path, target: Path) -> dict[str, Any]:
    missing = [str(source_dir / name) for name in DATABASE_OWNERS if not (source_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing source databases: {', '.join(missing)}")
    if target.exists():
        raise FileExistsError(f"target already exists: {target}")
    return {
        "source_dir": str(source_dir.resolve()),
        "personal_source": str(personal_source.resolve()),
        "target": str(target.resolve()),
        "databases": {name: database_manifest(source_dir / name) for name in DATABASE_OWNERS},
        "personal_storage": storage_manifest(personal_source),
    }


def migrate(
    source_dir: Path, personal_source: Path, target: Path, *, dry_run: bool = False
) -> dict[str, Any]:
    source = preflight(source_dir, personal_source, target)
    if dry_run:
        return {"dry_run": True, "source": source}

    staging = target.parent / f".{target.name}-staging-{uuid.uuid4().hex[:12]}"
    manifest: dict[str, Any] = {
        "migration_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": source,
        "target": {},
    }
    try:
        for name, owner in DATABASE_OWNERS.items():
            backup_database(source_dir / name, staging / owner / name)
        if personal_source.exists():
            shutil.copytree(personal_source, staging / "blobs" / "personal_knowledge")
        target_databases = {
            name: database_manifest(staging / owner / name) for name, owner in DATABASE_OWNERS.items()
        }
        target_storage = storage_manifest(staging / "blobs" / "personal_knowledge")
        for name in DATABASE_OWNERS:
            source_db = source["databases"][name]
            target_db = target_databases[name]
            if source_db["quick_check"] != "ok" or target_db["quick_check"] != "ok":
                raise RuntimeError(f"database integrity check failed: {name}")
            if source_db["tables"] != target_db["tables"]:
                raise RuntimeError(f"database row counts changed during migration: {name}")
        if source["personal_storage"] != target_storage:
            raise RuntimeError("personal knowledge file checksums changed during migration")
        for name, owner in DATABASE_OWNERS.items():
            target_databases[name]["path"] = str(target / owner / name)
        manifest["target"] = {
            "databases": target_databases,
            "personal_storage": target_storage,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        staging.replace(target)
        return {"dry_run": False, "target": str(target), "manifest": manifest}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a validated, rollback-safe Fab Insight V2 data set")
    parser.add_argument("--source-dir", type=Path, default=Path("data/departments"))
    parser.add_argument("--personal-source", type=Path, default=Path("data/personal_knowledge"))
    parser.add_argument("--target", type=Path, default=Path("data/v2"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = migrate(args.source_dir, args.personal_source, args.target, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
