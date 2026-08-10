from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import manage_databases


class DatabaseManagerTests(unittest.TestCase):
    def create_database(self, path: Path, table: str, rows: int = 2) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(f"CREATE TABLE {table} (id INTEGER)")
            connection.executemany(f"INSERT INTO {table} VALUES (?)", [(index,) for index in range(rows)])
            connection.commit()
        finally:
            connection.close()

    def test_manifest_uses_read_only_connections_and_reports_governance(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "main.db"
            self.create_database(database, "events", 3)
            original_connect = sqlite3.connect
            with (
                patch.object(manage_databases, "department_paths", return_value={"main": database}),
                patch.object(manage_databases, "TABLE_DEPARTMENTS", {"events": "main"}),
                patch.object(manage_databases, "validate_department_databases", return_value={"ok": True}),
                patch.object(manage_databases.sqlite3, "connect", wraps=original_connect) as connect,
            ):
                payload = manage_databases.manifest()
            self.assertEqual(payload["departments"]["manufacturing"]["tables"], {"events": 3})
            self.assertEqual(payload["departments"]["manufacturing"]["quick_check"], "ok")
            self.assertEqual(payload["governance"], {"ok": True})
            self.assertTrue(connect.call_args.args[0].endswith("?mode=ro"))
            self.assertTrue(connect.call_args.kwargs["uri"])

    def test_backup_publishes_only_complete_snapshot_and_uses_read_only_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "main.db"
            destination = root / "backups"
            self.create_database(database, "events")
            with (
                patch.object(manage_databases, "department_paths", return_value={"main": database}),
                patch.object(manage_databases, "TABLE_DEPARTMENTS", {"events": "main"}),
                patch.object(manage_databases, "validate_department_databases", return_value={"ok": True}),
                patch.object(manage_databases, "datetime", wraps=manage_databases.datetime) as clock,
            ):
                clock.now.return_value = manage_databases.datetime(2026, 8, 10, tzinfo=manage_databases.timezone.utc)
                result = manage_databases.backup(destination)
            backup_dir = Path(result["backup_dir"])
            self.assertTrue((backup_dir / "main.db").is_file())
            self.assertEqual(json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))["governance"], {"ok": True})
            copied = sqlite3.connect(f"file:{backup_dir / 'main.db'}?mode=ro", uri=True)
            try:
                self.assertEqual(copied.execute("SELECT COUNT(*) FROM events").fetchone()[0], 2)
            finally:
                copied.close()

    def test_backup_cleans_staging_directory_on_failure_and_does_not_overwrite_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "main.db"
            destination = root / "backups"
            self.create_database(database, "events")
            fixed_time = manage_databases.datetime(2026, 8, 10, tzinfo=manage_databases.timezone.utc)
            with (
                patch.object(manage_databases, "department_paths", return_value={"main": database}),
                patch.object(manage_databases, "manifest", side_effect=RuntimeError("manifest failed")),
                patch.object(manage_databases, "datetime", wraps=manage_databases.datetime) as clock,
            ):
                clock.now.return_value = fixed_time
                with self.assertRaisesRegex(RuntimeError, "manifest failed"):
                    manage_databases.backup(destination)
            self.assertEqual(list(destination.iterdir()), [])
            collision = destination / "20260810T000000Z"
            collision.mkdir()
            sentinel = collision / "keep"
            sentinel.write_text("unchanged", encoding="utf-8")
            with patch.object(manage_databases, "datetime", wraps=manage_databases.datetime) as clock:
                clock.now.return_value = fixed_time
                with self.assertRaises(FileExistsError):
                    manage_databases.backup(destination)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_main_dispatches_migrate_force_and_checkpoint(self):
        with (
            patch.object(manage_databases, "migrate_legacy_database", return_value={"main": 4}) as migrate,
            patch.object(manage_databases, "manifest", return_value={"ok": True}),
            patch("builtins.print") as output,
        ):
            self.assertEqual(manage_databases.main(["migrate", "--force"]), 0)
        migrate.assert_called_once_with(force=True)
        self.assertIn("migrated_rows", output.call_args.args[0])
        with patch.object(manage_databases, "checkpoint", return_value={"main": (0, 0, 0)}), patch("builtins.print") as output:
            self.assertEqual(manage_databases.main(["checkpoint"]), 0)
        self.assertIn('"main"', output.call_args.args[0])

    def test_checkpoint_runs_against_temporary_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "main.db"
            self.create_database(database, "events")
            with patch.object(manage_databases, "department_paths", return_value={"main": database}):
                result = manage_databases.checkpoint()
            self.assertEqual(len(result["main"]), 3)


if __name__ == "__main__":
    unittest.main()
