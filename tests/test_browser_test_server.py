from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.request import ProxyHandler

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
            with (
                patch.object(server, "backup_database") as backup,
                patch.object(server, "prepare_browser_test_model_capabilities") as prepare,
                patch.object(server, "prepare_browser_test_visual_fixtures") as prepare_visual,
                patch.object(server, "prepare_browser_test_journey_fixtures") as prepare_journey,
            ):
                environment = server.browser_test_environment(root, {
                    "FAB_MODEL_API_KEY": "secret", "FAB_REQUIRE_IDENTITY": "true", "FAB_DATA_PROVIDER": "live",
                    "DEEPSEEK_API_KEY": "legacy", "DEEPSEEK_MODEL": "host-model", "AGENT_LOG_CONTENT": "full",
                    "AGENT_RUN_LOG_DIR": "/host/logs", "FAB_ADMIN_API_TOKEN": "old", "FAB_WORKSPACE_ENV_FILE": "/host/.env",
                    "SAFE": "kept", "PATH": "/safe/path",
                })
            self.assertEqual(backup.call_count, 5)
            prepare.assert_called_once_with(Path(environment["FAB_AGENT_DATABASE_PATH"]))
            prepare_visual.assert_called_once_with(
                Path(environment["FAB_AGENT_DATABASE_PATH"]), Path(environment["FAB_KNOWLEDGE_DATABASE_PATH"])
            )
            prepare_journey.assert_called_once_with(
                Path(environment["FAB_AGENT_DATABASE_PATH"]), Path(environment["FAB_KNOWLEDGE_DATABASE_PATH"])
            )
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
            isolated_path_keys = (
                *server.DEPARTMENT_DATABASES,
                "FAB_DATABASE_PATH",
                "FAB_PERSONAL_KNOWLEDGE_STORAGE_PATH",
                "AGENT_LOG_PATH",
                "AGENT_RUN_LOG_DIR",
            )
            for key in isolated_path_keys:
                self.assertTrue(Path(environment[key]).is_relative_to(root))

    def test_model_capability_fixture_only_updates_the_temporary_agent_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "isolated"
            reference = server.REFERENCE_DEPARTMENTS / "ai_operations.db"
            with closing(sqlite3.connect(reference)) as connection:
                before_reference_rows = connection.execute(
                    "SELECT model_id, capabilities_json FROM model_catalog WHERE model_id IN (?, ?) ORDER BY model_id",
                    tuple(server.BROWSER_TEST_MODEL_CAPABILITIES),
                ).fetchall()
            environment = server.browser_test_environment(root, {})
            snapshot = Path(environment["FAB_AGENT_DATABASE_PATH"])
            with closing(sqlite3.connect(snapshot)) as connection:
                capabilities = dict(connection.execute(
                    "SELECT model_id, capabilities_json FROM model_catalog WHERE model_id IN (?, ?)",
                    tuple(server.BROWSER_TEST_MODEL_CAPABILITIES),
                ))
            with closing(sqlite3.connect(reference)) as connection:
                after_reference_rows = connection.execute(
                    "SELECT model_id, capabilities_json FROM model_catalog WHERE model_id IN (?, ?) ORDER BY model_id",
                    tuple(server.BROWSER_TEST_MODEL_CAPABILITIES),
                ).fetchall()
            self.assertEqual(
                {model_id: json.loads(value) for model_id, value in capabilities.items()},
                server.BROWSER_TEST_MODEL_CAPABILITIES,
            )
            self.assertEqual(after_reference_rows, before_reference_rows)

    def test_visual_fixtures_only_update_temporary_agent_and_knowledge_snapshots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "isolated"
            agent_snapshot = root / "agent.db"
            knowledge_snapshot = root / "knowledge.db"
            server.backup_database(server.REFERENCE_DEPARTMENTS / "ai_operations.db", agent_snapshot)
            server.backup_database(server.REFERENCE_DEPARTMENTS / "process_knowledge.db", knowledge_snapshot)
            server.prepare_browser_test_visual_fixtures(agent_snapshot, knowledge_snapshot)
            with closing(sqlite3.connect(agent_snapshot)) as connection:
                session = connection.execute(
                    "SELECT tenant_id, owner_user_id FROM chat_sessions WHERE session_id = ?",
                    (server.BROWSER_TEST_VISUAL_SESSION_ID,),
                ).fetchone()
                answer = connection.execute(
                    "SELECT content FROM chat_messages WHERE session_id = ? AND role = 'assistant'",
                    (server.BROWSER_TEST_VISUAL_SESSION_ID,),
                ).fetchone()
            with closing(sqlite3.connect(knowledge_snapshot)) as connection:
                document = connection.execute(
                    "SELECT filename, status FROM personal_knowledge_documents WHERE document_id = ?",
                    (server.BROWSER_TEST_VISUAL_DOCUMENT_ID,),
                ).fetchone()
                chunk = connection.execute(
                    "SELECT content FROM personal_knowledge_chunks WHERE document_id = ?",
                    (server.BROWSER_TEST_VISUAL_DOCUMENT_ID,),
                ).fetchone()
            self.assertEqual(tuple(session), (server.BROWSER_TEST_VISUAL_TENANT_ID, server.BROWSER_TEST_VISUAL_USER_ID))
            self.assertIn("CVD-02", answer[0])
            self.assertEqual(tuple(document), (server.BROWSER_TEST_VISUAL_DOCUMENT_FILENAME, "ready"))
            self.assertIn("CMP polishing response", chunk[0])
            with closing(sqlite3.connect(server.REFERENCE_DEPARTMENTS / "ai_operations.db")) as connection:
                self.assertIsNone(connection.execute(
                    "SELECT 1 FROM chat_sessions WHERE session_id = ?", (server.BROWSER_TEST_VISUAL_SESSION_ID,)
                ).fetchone())
            with closing(sqlite3.connect(server.REFERENCE_DEPARTMENTS / "process_knowledge.db")) as connection:
                self.assertIsNone(connection.execute(
                    "SELECT 1 FROM personal_knowledge_documents WHERE document_id = ?", (server.BROWSER_TEST_VISUAL_DOCUMENT_ID,)
                ).fetchone())

    def test_model_capability_fixture_fails_clearly_when_a_required_model_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "agent.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    "CREATE TABLE model_catalog (model_id TEXT PRIMARY KEY, capabilities_json TEXT NOT NULL)"
                )
                connection.execute("INSERT INTO model_catalog VALUES (?, ?)", ("deepseekv4-flash", "{}"))
                connection.commit()
            with self.assertRaisesRegex(RuntimeError, "deepseekv4-pro"):
                server.prepare_browser_test_model_capabilities(database)

    def test_journey_fixtures_are_isolated_and_provide_two_chunks_per_document(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            agent_snapshot, knowledge_snapshot = root / "agent.db", root / "knowledge.db"
            server.backup_database(server.REFERENCE_DEPARTMENTS / "ai_operations.db", agent_snapshot)
            server.backup_database(server.REFERENCE_DEPARTMENTS / "process_knowledge.db", knowledge_snapshot)
            server.prepare_browser_test_journey_fixtures(agent_snapshot, knowledge_snapshot)
            with closing(sqlite3.connect(agent_snapshot)) as connection:
                session = connection.execute("SELECT tenant_id, owner_user_id FROM chat_sessions WHERE session_id = ?", (server.BROWSER_TEST_JOURNEY_SESSION_ID,)).fetchone()
                metadata = json.loads(connection.execute("SELECT metadata_json FROM chat_messages WHERE session_id = ? AND role = 'assistant'", (server.BROWSER_TEST_JOURNEY_SESSION_ID,)).fetchone()[0])
            with closing(sqlite3.connect(knowledge_snapshot)) as connection:
                personal_owners = {
                    row[0]
                    for row in connection.execute(
                        "SELECT owner_user_id FROM personal_knowledge_documents WHERE document_id = ? "
                        "UNION SELECT owner_user_id FROM personal_knowledge_chunks WHERE document_id = ? "
                        "UNION SELECT owner_user_id FROM personal_knowledge_fts WHERE document_id = ?",
                        (server.BROWSER_TEST_JOURNEY_PERSONAL_DOCUMENT_ID,) * 3,
                    )
                }
                chunks = connection.execute("SELECT count(*) FROM personal_knowledge_chunks WHERE document_id = ?", (server.BROWSER_TEST_JOURNEY_PERSONAL_DOCUMENT_ID,)).fetchone()[0]
                factory = connection.execute("SELECT count(*) FROM knowledge_chunks WHERE source = ?", (server.BROWSER_TEST_JOURNEY_FACTORY_SOURCE,)).fetchone()[0]
                case = connection.execute("SELECT title FROM historical_cases WHERE case_id = ?", (server.BROWSER_TEST_JOURNEY_CASE_ID,)).fetchone()
            self.assertEqual(tuple(session), (server.BROWSER_TEST_JOURNEY_TENANT_ID, server.BROWSER_TEST_JOURNEY_USER_ID))
            self.assertEqual(personal_owners, {server.BROWSER_TEST_JOURNEY_KNOWLEDGE_OWNER_ID})
            self.assertEqual((chunks, factory), (2, 2))
            self.assertEqual(case[0], "QA009 CVD 历史案例")
            self.assertEqual(metadata["run_id"], "qa009-trace-run")
            self.assertEqual(len(metadata["tool_trace"]), 1)
            sources = metadata["sources"]
            self.assertEqual({item["source_type"] for item in sources}, {"personal", "knowledge", "case"})
            self.assertEqual(sum(item["source_type"] == "personal" for item in sources), 2)
            self.assertEqual(sum(item["source_type"] == "knowledge" for item in sources), 2)
            with closing(sqlite3.connect(server.REFERENCE_DEPARTMENTS / "ai_operations.db")) as connection:
                self.assertIsNone(connection.execute("SELECT 1 FROM chat_sessions WHERE session_id = ?", (server.BROWSER_TEST_JOURNEY_SESSION_ID,)).fetchone())
            with closing(sqlite3.connect(server.REFERENCE_DEPARTMENTS / "process_knowledge.db")) as connection:
                self.assertIsNone(connection.execute("SELECT 1 FROM personal_knowledge_documents WHERE document_id = ?", (server.BROWSER_TEST_JOURNEY_PERSONAL_DOCUMENT_ID,)).fetchone())
                self.assertIsNone(connection.execute("SELECT 1 FROM knowledge_documents WHERE source = ?", (server.BROWSER_TEST_JOURNEY_FACTORY_SOURCE,)).fetchone())
                self.assertIsNone(connection.execute("SELECT 1 FROM historical_cases WHERE case_id = ?", (server.BROWSER_TEST_JOURNEY_CASE_ID,)).fetchone())

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
        self.assertEqual(server.compatibility_fixture_port(8899), 8900)
        with self.assertRaisesRegex(ValueError, "leave room"):
            server.compatibility_fixture_port(65535)

    def test_fixture_key_cannot_persist_in_browser_test_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "safe.json").write_text('{"status":"ok"}', encoding="utf-8")
            server.scan_browser_test_artifacts(root)
            (root / "leak.log").write_text(server.BROWSER_TEST_FIXTURE_KEY, encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "fixture key leaked"):
                server.scan_browser_test_artifacts(root)

    def test_stage_messages_are_bounded_and_identify_startup_phases(self):
        self.assertEqual(
            server.stage_message("snapshot-preparation", status="start"),
            "browser-test stage=snapshot-preparation status=start",
        )
        self.assertEqual(
            server.stage_message("port-start", host="127.0.0.1", port=8899),
            "browser-test stage=port-start host=127.0.0.1 port=8899",
        )
        self.assertEqual(
            server.stage_message("health-ready", url="http://127.0.0.1:8899/api/health"),
            "browser-test stage=health-ready url=http://127.0.0.1:8899/api/health",
        )
        with self.assertRaisesRegex(ValueError, "unsupported browser-test stage"):
            server.stage_message("outside-loopback")

    def test_loopback_health_probe_accepts_only_the_app_health_route(self):
        responses = [OSError("not ready"), type("Response", (), {"status": 200, "close": lambda self: None})()]
        clock_values = iter((0.0, 0.0, 0.1, 0.1, 0.2))

        def opener(url, timeout):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        self.assertTrue(server.wait_for_loopback_health(
            "http://127.0.0.1:8899/api/health", timeout_seconds=1, opener=opener,
            sleeper=lambda seconds: None, clock=lambda: next(clock_values),
        ))
        with self.assertRaisesRegex(ValueError, "loopback /api/health"):
            server.wait_for_loopback_health("http://example.test/api/health")
        with self.assertRaisesRegex(ValueError, "loopback /api/health"):
            server.wait_for_loopback_health("http://127.0.0.1:8899/not-health")

    def test_default_loopback_health_opener_disables_environment_proxies(self):
        self.assertIsInstance(server.DIRECT_LOOPBACK_PROXY_HANDLER, ProxyHandler)
        self.assertEqual(server.DIRECT_LOOPBACK_PROXY_HANDLER.proxies, {})


if __name__ == "__main__":
    unittest.main()
