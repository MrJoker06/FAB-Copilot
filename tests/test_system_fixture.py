from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
import gc
import warnings
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tests.system import support


class SystemFixtureTests(unittest.TestCase):
    def setUp(self):
        support._cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.reference = Path(self.temporary.name) / "reference"
        self.reference.mkdir()
        for name in (
            "manufacturing_operations.db", "equipment_engineering.db", "yield_quality.db",
            "process_knowledge.db", "ai_operations.db",
        ):
            with closing(sqlite3.connect(self.reference / name)) as connection:
                connection.execute("CREATE TABLE sample (value TEXT)")
                connection.execute("INSERT INTO sample VALUES (?)", (name,))
                connection.commit()

    def tearDown(self):
        support._cleanup()
        self.temporary.cleanup()

    def test_fixture_overrides_every_database_path_with_readable_snapshots(self):
        with patch.object(support, "REFERENCE_DEPARTMENTS", self.reference), patch.dict(os.environ, {
            "FAB_MANUFACTURING_DATABASE_PATH": "/host/manufacturing.db",
            "FAB_EQUIPMENT_DATABASE_PATH": "/host/equipment.db",
            "FAB_QUALITY_DATABASE_PATH": "/host/quality.db",
            "FAB_KNOWLEDGE_DATABASE_PATH": "/host/knowledge.db",
            "FAB_AGENT_DATABASE_PATH": "/host/agent.db",
        }, clear=False):
            root = support.isolated_system_environment()
            for variable in (
                "FAB_MANUFACTURING_DATABASE_PATH", "FAB_EQUIPMENT_DATABASE_PATH", "FAB_QUALITY_DATABASE_PATH",
                "FAB_KNOWLEDGE_DATABASE_PATH", "FAB_AGENT_DATABASE_PATH",
            ):
                path = Path(os.environ[variable])
                self.assertTrue(path.is_relative_to(root))
                with closing(sqlite3.connect(path)) as connection:
                    self.assertEqual(connection.execute("SELECT value FROM sample").fetchone()[0], path.name)
            self.assertTrue(Path(os.environ["FAB_DATABASE_PATH"]).is_relative_to(root))
            self.assertTrue(Path(os.environ["FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH"]).is_relative_to(root))
            self.assertTrue(Path(os.environ["AGENT_LOG_PATH"]).is_relative_to(root))
            self.assertTrue(Path(os.environ["AGENT_RUN_LOG_DIR"]).is_relative_to(root))

    def test_fixture_failure_cleans_up_and_can_retry(self):
        calls = 0
        original_backup = support._backup_database

        def flaky_backup(source, destination):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("snapshot failed")
            original_backup(source, destination)

        with patch.object(support, "REFERENCE_DEPARTMENTS", self.reference), patch.object(support, "_backup_database", side_effect=flaky_backup):
            with self.assertRaises(OSError):
                support.isolated_system_environment()
            self.assertIsNone(support._temporary_directory)
            root = support.isolated_system_environment()
        self.assertTrue(root.exists())

    def test_missing_reference_database_fails_without_creating_source(self):
        missing = self.reference / "missing.db"
        with self.assertRaises(sqlite3.OperationalError):
            support._backup_database(missing, Path(self.temporary.name) / "snapshot.db")
        self.assertFalse(missing.exists())

    def test_backup_closes_source_and_target_connections(self):
        destination = Path(self.temporary.name) / "snapshot.db"
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            support._backup_database(self.reference / "ai_operations.db", destination)
            gc.collect()
        with closing(sqlite3.connect(destination)) as connection:
            self.assertEqual(connection.execute("SELECT value FROM sample").fetchone()[0], "ai_operations.db")
