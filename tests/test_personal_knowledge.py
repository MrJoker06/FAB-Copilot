from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app.database import _migrate_personal_knowledge_tags_source
from app.personal_knowledge import ExtractedSection, _automatic_tags, _normalise_tags, search_personal_knowledge


class PersonalKnowledgeTagTests(unittest.TestCase):
    def test_legacy_tags_source_migration_is_one_time(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            "CREATE TABLE personal_knowledge_documents (document_id TEXT, tags_json TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO personal_knowledge_documents VALUES (?, ?)",
            [("human", '["maintained"]'), ("automatic", "[]")],
        )
        _migrate_personal_knowledge_tags_source(connection)
        sources = dict(connection.execute(
            "SELECT document_id, tags_source FROM personal_knowledge_documents"
        ))
        self.assertEqual(sources, {"human": "user", "automatic": "auto"})
        connection.execute("UPDATE personal_knowledge_documents SET tags_json = '[\"ETCH\"]' WHERE document_id = 'automatic'")
        _migrate_personal_knowledge_tags_source(connection)
        self.assertEqual(
            connection.execute("SELECT tags_source FROM personal_knowledge_documents WHERE document_id = 'automatic'").fetchone()[0],
            "auto",
        )

    def test_automatic_tags_use_governed_topics_and_document_types(self):
        tags = _automatic_tags(
            "ETCH-07 maintenance report",
            "etch-maintenance.md",
            [ExtractedSection(None, "summary", "ETCH-07 reported a Scratch alarm after PM maintenance.")],
        )
        self.assertTrue({"ETCH", "ETCH-07", "REPORT", "MAINTENANCE", "SCRATCH", "ALARM", "MD"}.issubset(tags))
        normalized = _normalise_tags([" Alpha ", "alpha", *[f"tag-{index}" for index in range(40)]])
        self.assertEqual(normalized[0], "Alpha")
        self.assertEqual(len(normalized), 30)

    def test_tag_element_matching_does_not_use_substrings(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE documents (tags_json TEXT NOT NULL)")
        connection.execute("INSERT INTO documents VALUES ('[\"sketch\"]')")
        exact = connection.execute(
            "SELECT COUNT(*) FROM documents d WHERE EXISTS "
            "(SELECT 1 FROM json_each(d.tags_json) tag WHERE LOWER(TRIM(tag.value)) IN (?))",
            ("etch",),
        ).fetchone()[0]
        self.assertEqual(exact, 0)

    def test_search_uses_exact_tag_elements_before_fts(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("ATTACH DATABASE ':memory:' AS knowledge")
        connection.executescript("""
            CREATE TABLE personal_knowledge_documents (
                document_id TEXT PRIMARY KEY, owner_user_id TEXT, title TEXT, filename TEXT,
                process_steps_json TEXT, equipment_ids_json TEXT, tags_json TEXT, tags_source TEXT,
                effective_date TEXT, status TEXT, updated_at TEXT
            );
            CREATE TABLE personal_knowledge_chunks (
                chunk_id TEXT PRIMARY KEY, document_id TEXT, owner_user_id TEXT, section_path TEXT,
                page_number INTEGER, chunk_index INTEGER, content TEXT
            );
        """)
        connection.execute("""CREATE VIRTUAL TABLE knowledge.personal_knowledge_fts USING fts5(
            title, section_path, content, owner_user_id UNINDEXED, document_id UNINDEXED,
            chunk_id UNINDEXED, tokenize='trigram')""")
        documents = [
            ("d1", "owner", "plain", "one.md", "[]", "[]", '["needle"]', "user", None, "ready", "2026-01-01"),
            ("d2", "owner", "plain", "two.md", "[]", "[]", '["needle"]', "auto", None, "ready", "2026-01-02"),
            ("d3", "owner", "plain", "three.md", "[]", "[]", '["sketch"]', "user", None, "ready", "2026-01-03"),
            ("d4", "other", "plain", "four.md", "[]", "[]", '["needle"]', "user", None, "ready", "2026-01-04"),
        ]
        connection.executemany("INSERT INTO personal_knowledge_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", documents)
        for document_id, owner, *_ in documents:
            connection.execute(
                "INSERT INTO personal_knowledge_chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"chunk-{document_id}", document_id, owner, "body", None, 0, "needle" if document_id == "d2" else "plain"),
            )
            connection.execute(
                "INSERT INTO knowledge.personal_knowledge_fts "
                "(title, section_path, content, owner_user_id, document_id, chunk_id) VALUES (?, ?, ?, ?, ?, ?)",
                ("plain", "body", "needle" if document_id == "d2" else "plain", owner, document_id, f"chunk-{document_id}"),
            )

        @contextmanager
        def fake_session():
            yield connection

        with patch("app.personal_knowledge.db_session", fake_session):
            results = search_personal_knowledge("owner", "needle", limit=3)
            self.assertEqual([item["document_id"] for item in results], ["d2", "d1"])
            self.assertEqual(results[0]["tags_source"], "auto")
            self.assertEqual(search_personal_knowledge("owner", "etch", limit=3), [])
            self.assertEqual(
                [item["document_id"] for item in search_personal_knowledge("owner", "needle", limit=1, document_ids=["d1"])],
                ["d1"],
            )


if __name__ == "__main__":
    unittest.main()
