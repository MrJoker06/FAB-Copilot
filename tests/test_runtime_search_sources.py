from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agent_runtime.tools.contracts import ToolSourceKind
from app.tools.knowledge_search.runtime_search import (
    _quality_aliases,
    _readonly_session,
    create_runtime_knowledge_port,
)
from app.tools.knowledge_search.contracts import (
    KnowledgeSearchDataError,
    KnowledgeSearchQuery,
    KnowledgeSearchTimeoutError,
)
from app.knowledge.sqlite_backend import SqliteFactorySearchBackend
from app.persistence.department_schemas import KNOWLEDGE_SCHEMA, QUALITY_SCHEMA


class RuntimeSearchSourcesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.knowledge, self.quality = root / "knowledge.db", root / "quality.db"
        self._knowledge_fixture()
        connection = sqlite3.connect(self.quality)
        connection.executescript(QUALITY_SCHEMA)
        connection.execute(
            "INSERT INTO defect_types(canonical_name,is_active) VALUES('Particles',1)"
        )
        connection.execute(
            "INSERT INTO defect_type_aliases(defect_type_id,alias) VALUES(1,'颗粒')"
        )
        connection.commit()
        connection.close()
        self.settings = SimpleNamespace(
            factory_search_backend="sqlite",
            enterprise_default_tenant_id="demo",
            knowledge_database_path=self.knowledge,
            quality_database_path=self.quality,
        )
        self.principal = SimpleNamespace(
            tenant_id="demo", user_id="alice", roles=("analyst",)
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _knowledge_fixture(self) -> None:
        connection = sqlite3.connect(self.knowledge)
        connection.executescript(KNOWLEDGE_SCHEMA)
        connection.execute(
            "INSERT INTO knowledge_documents VALUES('sop.md','Particle SOP','SOP','1','Active','2026-01-01','fab',5,'LITHO','LITHO','particles')"
        )
        connection.execute(
            "INSERT INTO knowledge_chunks(title,source,section,content) VALUES('Particle SOP','sop.md','guide','LITHO particle control')"
        )
        connection.execute(
            "INSERT INTO knowledge_trigram_fts(rowid,title,section,content) VALUES(1,'Particle SOP','guide','LITHO particle control')"
        )
        connection.execute(
            """INSERT INTO personal_knowledge_documents VALUES('doc','alice','a.txt','Private SOP','text/plain',1,'x','[\"LITHO\"]','[]',NULL,'[\"particles\"]','user','ready','x','v',NULL,NULL,'i','2026','2026')"""
        )
        connection.execute(
            "INSERT INTO personal_knowledge_chunks(chunk_id,document_id,owner_user_id,page_number,section_path,chunk_index,content,token_count,created_at) VALUES('chunk','doc','alice',1,'note',0,'private particle note',3,'2026')"
        )
        connection.execute(
            "INSERT INTO personal_knowledge_fts(title,section_path,content,owner_user_id,document_id,chunk_id) VALUES('Private SOP','note','private particle note','alice','doc','chunk')"
        )
        connection.commit()
        connection.close()

    def test_sqlite_source_reads_aliases_and_personal_knowledge_without_other_databases(
        self,
    ) -> None:
        port = create_runtime_knowledge_port(
            settings=self.settings, principal=self.principal
        )
        query = KnowledgeSearchQuery("particle", source_types=("knowledge", "personal"))
        snapshot = port.fetch(query, self.principal)
        self.assertEqual(snapshot.aliases["Particles"], ("Particles", "颗粒"))
        self.assertEqual(
            {row["source_type"] for row in snapshot.candidates},
            {"knowledge", "personal"},
        )
        self.assertEqual(
            {source.source_kind for source in snapshot.sources}, {ToolSourceKind.SQLITE}
        )
        self.assertEqual(snapshot.owner_user_id, "alice")

    def test_missing_sources_fail_closed_without_creating_files(self) -> None:
        missing = Path(self.directory.name) / "missing.db"
        settings = SimpleNamespace(
            factory_search_backend="sqlite",
            enterprise_default_tenant_id="demo",
            knowledge_database_path=missing,
            quality_database_path=missing,
        )
        port = create_runtime_knowledge_port(
            settings=settings, principal=self.principal
        )
        with self.assertRaises(KnowledgeSearchDataError):
            port.fetch(
                KnowledgeSearchQuery("particle", source_types=("knowledge",)),
                self.principal,
            )
        self.assertFalse(missing.exists())

    def test_readonly_session_mounts_only_knowledge_and_rejects_writes(self) -> None:
        session = _readonly_session(self.knowledge)
        with session() as connection:
            names = [row[1] for row in connection.execute("PRAGMA database_list")]
            self.assertEqual(names, ["main", "knowledge"])
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE forbidden (value TEXT)")

    def test_non_default_tenant_personal_owner_is_isolated(self) -> None:
        foreign_owner = "other:alice"
        connection = sqlite3.connect(self.knowledge)
        connection.execute(
            "INSERT INTO personal_knowledge_documents VALUES(?, ?, 'b.txt', 'Other SOP', "
            "'text/plain', 1, 'x', '[]', '[]', NULL, '[\"particles\"]', 'user', "
            "'ready', 'x', 'v', NULL, NULL, 'i', '2026', '2026')",
            ("other-doc", foreign_owner),
        )
        connection.execute(
            "INSERT INTO personal_knowledge_chunks(chunk_id, document_id, owner_user_id, "
            "page_number, section_path, chunk_index, content, token_count, created_at) "
            "VALUES('other-chunk', 'other-doc', ?, 1, 'note', 0, 'other particle note', 3, '2026')",
            (foreign_owner,),
        )
        connection.execute(
            "INSERT INTO personal_knowledge_fts VALUES('Other SOP', 'note', "
            "'other particle note', ?, 'other-doc', 'other-chunk')",
            (foreign_owner,),
        )
        connection.commit()
        connection.close()
        principal = SimpleNamespace(
            tenant_id="other", user_id="alice", roles=("analyst",)
        )
        port = create_runtime_knowledge_port(
            settings=self.settings, principal=principal
        )
        snapshot = port.fetch(
            KnowledgeSearchQuery("particle", source_types=("personal",)), principal
        )
        self.assertEqual(snapshot.owner_user_id, foreign_owner)
        self.assertEqual(
            [
                row["reference_id"]
                for row in snapshot.candidates
                if row["source_type"] == "personal"
            ],
            ["PERSONAL-other-chunk"],
        )

    def test_custom_factory_keeps_personal_read_and_truthful_source_kind(self) -> None:
        class CustomFactory:
            tool_source_kind = ToolSourceKind.KNOWLEDGE

            def defect_aliases(self, principal):
                return {"Particles": ("Particles",)}

            def search(self, principal, request):
                return [
                    {
                        "source_type": "knowledge",
                        "reference_id": "company-1",
                        "status": "Active",
                    }
                ]

        custom_settings = SimpleNamespace(
            factory_search_backend="company",
            enterprise_default_tenant_id="demo",
            knowledge_database_path=self.knowledge,
            quality_database_path=self.quality,
        )
        with patch(
            "app.tools.knowledge_search.runtime_search.get_factory_search_backend",
            return_value=CustomFactory(),
        ):
            port = create_runtime_knowledge_port(
                settings=custom_settings, principal=self.principal
            )
            snapshot = port.fetch(
                KnowledgeSearchQuery(
                    "particle", source_types=("knowledge", "personal")
                ),
                self.principal,
            )
        self.assertEqual(
            {row["source_type"] for row in snapshot.candidates},
            {"knowledge", "personal"},
        )
        self.assertEqual(
            {source.source_kind for source in snapshot.sources},
            {ToolSourceKind.KNOWLEDGE, ToolSourceKind.SQLITE},
        )

    def test_custom_factory_without_source_kind_is_rejected(self) -> None:
        class UntypedFactory:
            def defect_aliases(self, principal):
                return {}

            def search(self, principal, request):
                return []

        settings = SimpleNamespace(
            factory_search_backend="company",
            enterprise_default_tenant_id="demo",
            knowledge_database_path=self.knowledge,
            quality_database_path=self.quality,
        )
        with (
            patch(
                "app.tools.knowledge_search.runtime_search.get_factory_search_backend",
                return_value=UntypedFactory(),
            ),
            self.assertRaises(ValueError),
        ):
            create_runtime_knowledge_port(settings=settings, principal=self.principal)

    def test_alias_reader_receives_principal(self) -> None:
        seen = []
        backend = SqliteFactorySearchBackend(
            alias_reader=lambda principal: seen.append(principal) or {"D": ("D",)}
        )
        self.assertEqual(backend.defect_aliases(self.principal), {"D": ("D",)})
        self.assertEqual(seen, [self.principal])

    def test_quality_timeout_wins_over_close_failure(self) -> None:
        class InterruptedConnection:
            row_factory = None

            def execute(self, sql, *args):
                if "SELECT" in sql:
                    raise sqlite3.OperationalError("interrupted")
                return self

            def set_progress_handler(self, *args):
                return None

            def close(self):
                raise RuntimeError("close failure")

        with (
            patch(
                "app.tools.knowledge_search.runtime_search.sqlite3.connect",
                return_value=InterruptedConnection(),
            ),
            self.assertRaises(KnowledgeSearchTimeoutError),
        ):
            _quality_aliases(self.quality)(self.principal)

    def test_session_cleanup_always_closes_and_body_timeout_wins(self) -> None:
        class ResetFailureConnection:
            row_factory = None

            def __init__(self, *, interrupted: bool) -> None:
                self.interrupted = interrupted
                self.closed = False

            def execute(self, sql, *args):
                if self.interrupted and sql.startswith("SELECT"):
                    raise sqlite3.OperationalError("interrupted")
                return self

            def set_progress_handler(self, callback, _count):
                if callback is None:
                    raise RuntimeError("reset failure")

            def close(self):
                self.closed = True

        timeout_connection = ResetFailureConnection(interrupted=True)
        with (
            patch(
                "app.tools.knowledge_search.runtime_search.sqlite3.connect",
                return_value=timeout_connection,
            ),
            self.assertRaises(KnowledgeSearchTimeoutError),
            _readonly_session(self.knowledge)() as connection,
        ):
            connection.execute("SELECT 1")
        self.assertTrue(timeout_connection.closed)

        clean_connection = ResetFailureConnection(interrupted=False)
        with (
            patch(
                "app.tools.knowledge_search.runtime_search.sqlite3.connect",
                return_value=clean_connection,
            ),
            self.assertRaisesRegex(RuntimeError, "reset failure"),
            _readonly_session(self.knowledge)(),
        ):
            pass
        self.assertTrue(clean_connection.closed)

    def test_quality_alias_cleanup_closes_after_reset_failure(self) -> None:
        class ResetFailureConnection:
            row_factory = None

            def __init__(self) -> None:
                self.closed = False

            def execute(self, sql, *args):
                if "SELECT" in sql:
                    raise sqlite3.OperationalError("interrupted")
                return self

            def set_progress_handler(self, callback, _count):
                if callback is None:
                    raise RuntimeError("reset failure")

            def close(self):
                self.closed = True

        connection = ResetFailureConnection()
        with (
            patch(
                "app.tools.knowledge_search.runtime_search.sqlite3.connect",
                return_value=connection,
            ),
            self.assertRaises(KnowledgeSearchTimeoutError),
        ):
            _quality_aliases(self.quality)(self.principal)
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
