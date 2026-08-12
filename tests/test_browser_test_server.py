from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts import run_browser_test_server as server


class BrowserTestServerTests(unittest.TestCase):
    def test_backup_requires_existing_source_without_creating_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "missing.db"
            destination = Path(temporary) / "snapshot.db"
            with self.assertRaises(FileNotFoundError):
                server.backup_database(source, destination)
            self.assertFalse(source.exists())
            self.assertFalse(destination.exists())

    def test_environment_removes_hostile_app_values_and_keeps_safe_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "isolated"
            with patch.object(server, "backup_database") as backup:
                environment = server.browser_test_environment(root, {
                    "FAB_MODEL_API_KEY": "secret", "FAB_REQUIRE_IDENTITY": "true", "FAB_DATA_PROVIDER": "live",
                    "DEEPSEEK_API_KEY": "legacy", "DEEPSEEK_MODEL": "host-model", "AGENT_LOG_CONTENT": "full",
                    "AGENT_RUN_LOG_DIR": "/host/logs", "FAB_ADMIN_API_TOKEN": "old", "FAB_WORKSPACE_ENV_FILE": "/host/.env",
                    "SAFE": "kept", "PATH": "/safe/path",
                })
            self.assertEqual(backup.call_count, 5)
            self.assertEqual(environment["SAFE"], "kept")
            self.assertEqual(environment["PATH"], "/safe/path")
            self.assertEqual(environment["FAB_MODEL_API_KEY"], "")
            self.assertEqual(environment["DEEPSEEK_API_KEY"], "")
            self.assertEqual(environment["FAB_ADMIN_API_TOKEN"], server.BROWSER_TEST_ADMIN_TOKEN)
            self.assertEqual(environment["FAB_REQUIRE_IDENTITY"], "false")
            self.assertEqual(environment["FAB_DATA_PROVIDER"], "synthetic")
            self.assertEqual(environment["FAB_MODEL_PROVIDER"], "browser-test")
            self.assertEqual(environment["FAB_MODEL_NAME"], "browser-test-model")
            self.assertEqual(environment["FAB_MODEL_BASE_URL"], "http://127.0.0.1:9")
            self.assertEqual(environment["AGENT_LOG_CONTENT"], "metadata")
            self.assertEqual(environment["FAB_INSTANCE_ROOT"], str(root))
            self.assertEqual(environment["FAB_SOURCE_ROOT"], str(server.PROJECT_DIR))
            for key in (*server.DEPARTMENT_DATABASES, "FAB_DATABASE_PATH", "FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH", "AGENT_LOG_PATH", "AGENT_RUN_LOG_DIR"):
                self.assertTrue(Path(environment[key]).is_relative_to(root))

    def test_backup_uses_read_only_source_and_closes_connections(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.db"
            destination = Path(temporary) / "destination.db"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE items (value TEXT)")
                connection.execute("INSERT INTO items VALUES ('ok')")
                connection.commit()
            server.backup_database(source, destination)
            with closing(sqlite3.connect(destination)) as connection:
                self.assertEqual(connection.execute("SELECT value FROM items").fetchone()[0], "ok")

    def test_port_defaults_and_bounds(self):
        self.assertEqual(server.DEFAULT_PORT, 8899)
        self.assertEqual(server.parse_port("8899"), 8899)
        for value in ("1023", "65536"):
            with self.assertRaises(Exception):
                server.parse_port(value)


if __name__ == "__main__":
    unittest.main()
