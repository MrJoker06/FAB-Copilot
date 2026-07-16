from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.migrate_v2 import DATABASE_OWNERS, migrate


def _source_database(path: Path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES (?)", (value,))


def test_v2_migration_is_parallel_validated_and_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for name in DATABASE_OWNERS:
        _source_database(source / name, name)
    personal = tmp_path / "personal"
    personal.mkdir()
    (personal / "document.txt").write_text("private knowledge", encoding="utf-8")
    target = tmp_path / "v2"

    dry_run = migrate(source, personal, target, dry_run=True)
    assert dry_run["dry_run"] is True
    assert not target.exists()

    result = migrate(source, personal, target)
    assert result["target"] == str(target)
    assert (target / "manifest.json").exists()
    assert (target / "mcp" / "manufacturing_operations.db").exists()
    assert (target / "api" / "ai_operations.db").exists()
    assert (target / "blobs" / "personal_knowledge" / "document.txt").read_text() == "private knowledge"
    manifest = result["manifest"]
    assert all("staging" not in item["path"] for item in manifest["target"]["databases"].values())
    assert all((source / name).exists() for name in DATABASE_OWNERS)
    with pytest.raises(FileExistsError):
        migrate(source, personal, target)
