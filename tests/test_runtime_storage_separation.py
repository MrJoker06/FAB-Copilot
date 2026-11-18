"""Offline migration preserves real records and rejects unsafe layouts."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.settings import get_settings
from app.persistence import database
from app.persistence.department_schemas import (
    AGENT_SCHEMA,
    KNOWLEDGE_SCHEMA,
    PERSONAL_SCHEMA,
)
from app.personal_knowledge_runtime.search import search_knowledge


class RuntimeStorageSeparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.history = self.root / "process_knowledge.db"
        self.agent = self.root / "ai_operations.db"
        self.destination = self.root / "runtime" / "state"
        with closing(sqlite3.connect(self.history)) as connection:
            connection.executescript(KNOWLEDGE_SCHEMA + PERSONAL_SCHEMA)
            connection.execute("CREATE TABLE company_sentinel(value TEXT)")
            connection.execute(
                "INSERT INTO company_sentinel VALUES ('historical-only')"
            )
            connection.execute(
                "INSERT INTO knowledge_chunks(title,source,section,content) VALUES('SOP','old.md','body','historical particle')"
            )
            connection.execute(
                "INSERT INTO knowledge_trigram_fts(knowledge_trigram_fts) VALUES ('rebuild')"
            )
            connection.execute("""INSERT INTO personal_knowledge_documents(document_id,owner_user_id,filename,title,mime_type,size_bytes,checksum_sha256,status,storage_key,parser_version,idempotency_key,created_at,updated_at)
                VALUES('doc','alice','note.txt','Private SOP','text/plain',8,'fixture','ready','unchanged/original.txt','v1','upload-1','2026','2026')""")
            connection.execute(
                "INSERT INTO personal_knowledge_chunks(chunk_id,document_id,owner_user_id,section_path,chunk_index,content,token_count,created_at) VALUES('chunk','doc','alice','body',0,'private particle',2,'2026')"
            )
            connection.execute(
                "INSERT INTO personal_knowledge_jobs(job_id,document_id,owner_user_id,status,stage,progress,created_at,updated_at) VALUES('job','doc','alice','ready','complete',100,'2026','2026')"
            )
            connection.execute(
                "INSERT INTO personal_knowledge_fts(rowid,title,section_path,content,owner_user_id,document_id,chunk_id) VALUES(42,'Private SOP','body','private particle','alice','doc','chunk')"
            )
            connection.commit()
        with closing(sqlite3.connect(self.agent)) as connection:
            connection.executescript(AGENT_SCHEMA)
            connection.execute(
                "INSERT INTO chat_sessions(session_id,title,created_at,updated_at) VALUES('session','retained','2026','2026')"
            )
            connection.execute(
                "INSERT INTO model_catalog(model_id,display_name,provider,provider_model,base_url,status,capabilities_json,created_by,created_at,updated_at) VALUES('local-qwen','Local Qwen','local-qwen','qwen','http://127.0.0.1:9/v1','published','{\"thinking\":true}','admin','2026','2026')"
            )
            connection.execute("CREATE TABLE configuration_sentinel(value TEXT)")
            connection.execute(
                "INSERT INTO configuration_sentinel VALUES ('qwen-configuration-retained')"
            )
            connection.commit()
        self.results = self.root / "tool_results.db"
        with closing(sqlite3.connect(self.results)) as connection:
            connection.execute("CREATE TABLE result_reference(value TEXT)")
            connection.execute(
                "INSERT INTO result_reference VALUES ('retained-reference')"
            )
            connection.commit()

    def migrate(self, **kwargs):
        return database.separate_runtime_storage(
            self.history, self.agent, self.destination, results=self.results, **kwargs
        )

    def test_dry_run_does_not_write(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(self.migrate()["status"], "planned")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_migration_preserves_records_indexes_backups_and_user_isolation(self):
        outcome = self.migrate(apply=True)
        self.assertEqual(outcome["status"], "completed")
        with closing(sqlite3.connect(self.history)) as history:
            self.assertFalse(set(database.PERSONAL_TABLES) & database._tables(history))
            self.assertEqual(
                history.execute(
                    "SELECT content FROM knowledge_trigram_fts WHERE knowledge_trigram_fts MATCH 'particle'"
                ).fetchall(),
                [("historical particle",)],
            )
            self.assertEqual(
                history.execute("SELECT * FROM company_sentinel").fetchall(),
                [("historical-only",)],
            )
        with closing(
            sqlite3.connect(self.destination / "personal_knowledge.db")
        ) as personal:
            self.assertFalse(
                {
                    "knowledge_documents",
                    "knowledge_chunks",
                    "historical_cases",
                    "company_sentinel",
                }
                & database._tables(personal)
            )
            self.assertEqual(
                personal.execute(
                    "SELECT storage_key FROM personal_knowledge_documents"
                ).fetchone()[0],
                "unchanged/original.txt",
            )
            self.assertEqual(
                personal.execute(
                    "SELECT rowid,content FROM personal_knowledge_fts WHERE personal_knowledge_fts MATCH 'particle'"
                ).fetchall(),
                [(42, "private particle")],
            )
            self.assertEqual(
                personal.execute(
                    "SELECT job_id,status FROM personal_knowledge_jobs"
                ).fetchall(),
                [("job", "ready")],
            )
        for name, table, expected in (
            (
                "ai_operations.db",
                "configuration_sentinel",
                "qwen-configuration-retained",
            ),
            ("tool_results.db", "result_reference", "retained-reference"),
        ):
            with closing(sqlite3.connect(self.destination / name)) as connection:
                self.assertEqual(
                    connection.execute(f"SELECT * FROM {table}").fetchall(),
                    [(expected,)],
                )
        with (
            closing(sqlite3.connect(self.agent)) as old,
            closing(sqlite3.connect(self.destination / "ai_operations.db")) as new,
        ):
            for table in ("model_catalog", "chat_sessions"):
                self.assertEqual(
                    old.execute(f"SELECT * FROM {table}").fetchall(),
                    new.execute(f"SELECT * FROM {table}").fetchall(),
                )
        with closing(sqlite3.connect(Path(outcome["backup"]) / "history.db")) as backup:
            self.assertEqual(
                backup.execute(
                    "SELECT document_id FROM personal_knowledge_documents"
                ).fetchall(),
                [("doc",)],
            )
        environment = {
            "FAB_KNOWLEDGE_DATABASE_PATH": str(self.history),
            "FAB_AGENT_DATABASE_PATH": str(self.destination / "ai_operations.db"),
            "FAB_PERSONAL_DATABASE_PATH": str(
                self.destination / "personal_knowledge.db"
            ),
        }
        with patch.dict(os.environ, environment):
            deps = SimpleNamespace(
                db_session=database.db_session,
                fts_query=lambda q: q,
                json_list=json.loads,
            )
            self.assertEqual(
                [
                    r["document_id"]
                    for r in search_knowledge(deps, "alice", "particle", 10)
                ],
                ["doc"],
            )
            self.assertEqual(search_knowledge(deps, "bob", "particle", 10), [])
        self.assertEqual(self.migrate(apply=True)["status"], "already_migrated")

    def test_populated_legacy_layout_refuses_silent_empty_initialization(self):
        with (
            patch.dict(
                os.environ,
                {
                    "FAB_KNOWLEDGE_DATABASE_PATH": str(self.history),
                    "FAB_AGENT_DATABASE_PATH": str(
                        self.destination / "ai_operations.db"
                    ),
                },
            ),
            self.assertRaisesRegex(RuntimeError, "MIGRATION_REQUIRED"),
        ):
            database.initialize()
        self.assertFalse(self.destination.exists())

    def test_existing_destination_and_duplicate_sources_are_rejected(self):
        self.destination.mkdir(parents=True)
        sentinel = self.destination / "keep"
        sentinel.write_text("owned", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.migrate(apply=True)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "owned")
        with self.assertRaisesRegex(ValueError, "PATH_CONFLICT"):
            database.separate_runtime_storage(
                self.history, self.history, self.root / "new", apply=True
            )

    def test_failed_validation_leaves_source_authoritative(self):
        with (
            patch.object(
                database,
                "_initialize_file",
                side_effect=RuntimeError("injected failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "injected failure"),
        ):
            self.migrate(apply=True)
        self.assertFalse(self.destination.exists())
        with closing(sqlite3.connect(self.history)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT document_id FROM personal_knowledge_documents"
                ).fetchall(),
                [("doc",)],
            )
        self.assertFalse(database._migration_marker(self.destination).exists())

    def test_interrupted_publish_blocks_readers_instead_of_appearing_successful(self):
        original = Path.replace

        def fail_receipt(path, target):
            if path.name == ".storage-separation.json.tmp":
                raise OSError("injected publish failure")
            return original(path, target)

        with (
            patch.object(Path, "replace", fail_receipt),
            self.assertRaisesRegex(OSError, "publish failure"),
        ):
            self.migrate(apply=True)
        self.assertTrue(database._migration_marker(self.destination).exists())
        with self.assertRaisesRegex(RuntimeError, "MIGRATION_PENDING"):
            self.migrate(apply=True)
        self.assertEqual(
            json.loads((self.destination / "storage-separation.json").read_text())[
                "status"
            ],
            "pending",
        )

    def test_settings_defaults_and_explicit_paths(self):
        with patch.dict(
            os.environ,
            {
                "FAB_PROJECT_ENV_FILE": str(self.root / "none"),
                "FAB_WORKSPACE_ENV_FILE": str(self.root / "none"),
                "FAB_RUNTIME_DATABASE_DIR": str(self.destination),
            },
            clear=True,
        ):
            settings = get_settings()
            self.assertEqual(
                settings.agent_database_path, self.destination / "ai_operations.db"
            )
            self.assertEqual(
                settings.personal_database_path,
                self.destination / "personal_knowledge.db",
            )
            self.assertEqual(
                settings.tool_result_database_path, self.destination / "tool_results.db"
            )
            with patch.dict(
                os.environ, {"FAB_AGENT_DATABASE_PATH": str(self.root / "custom.db")}
            ):
                self.assertEqual(
                    get_settings().personal_database_path,
                    self.root / "personal_knowledge.db",
                )

    def test_old_tag_schema_keeps_human_tags_and_empty_tag_semantics(self):
        with closing(sqlite3.connect(self.history)) as connection:
            connection.execute(
                "ALTER TABLE personal_knowledge_documents DROP COLUMN tags_source"
            )
            connection.execute(
                "UPDATE personal_knowledge_documents SET tags_json='[\"human\"]'"
            )
            connection.commit()
        self.migrate(apply=True)
        with closing(
            sqlite3.connect(self.destination / "personal_knowledge.db")
        ) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT tags_source FROM personal_knowledge_documents"
                ).fetchone()[0],
                "user",
            )

    def test_active_source_writer_prevents_migration_without_data_loss(self):
        with closing(sqlite3.connect(self.history)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                self.migrate(apply=True)
        self.assertFalse(self.destination.exists())
        with closing(sqlite3.connect(self.history)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT document_id FROM personal_knowledge_documents"
                ).fetchall(),
                [("doc",)],
            )
