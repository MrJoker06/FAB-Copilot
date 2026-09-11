from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import database
from app import department_schemas
from app import execution_store
from app.persistence import database as canonical_database
from app.persistence import department_schemas as canonical_department_schemas
from app.persistence import execution_store as canonical_execution_store
from scripts.check_module_boundaries import boundary_errors, load_manifest


class PersistenceModuleBoundaryTests(unittest.TestCase):
    def test_legacy_facades_retain_canonical_public_and_private_object_identity(self):
        self.assertIs(database.db_session, canonical_database.db_session)
        self.assertIs(database.initialize, canonical_database.initialize)
        self.assertIs(database.SCHEMA, canonical_database.SCHEMA)
        self.assertIs(
            database._migrate_model_health,
            canonical_database._migrate_model_health,
        )
        self.assertIs(department_schemas.SCHEMA_VERSION, canonical_department_schemas.SCHEMA_VERSION)
        self.assertIs(department_schemas.DEPARTMENT_SCHEMAS, canonical_department_schemas.DEPARTMENT_SCHEMAS)
        self.assertIs(execution_store.start_run_record, canonical_execution_store.start_run_record)
        self.assertIs(execution_store.RunExecutionRecorder, canonical_execution_store.RunExecutionRecorder)

    def test_canonical_db_session_closes_connections_and_requires_explicit_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "persistence.db"
            connection = None
            with canonical_database.db_session(path) as connection:
                connection.execute("CREATE TABLE records (value TEXT)")
                connection.execute("INSERT INTO records VALUES ('saved')")
                connection.commit()
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
            with sqlite3.connect(path) as verification:
                self.assertEqual(verification.execute("SELECT value FROM records").fetchone()[0], "saved")

            uncommitted_connection = None
            with canonical_database.db_session(path) as uncommitted_connection:
                uncommitted_connection.execute("INSERT INTO records VALUES ('normal exit rollback')")
            with self.assertRaises(sqlite3.ProgrammingError):
                uncommitted_connection.execute("SELECT 1")
            with sqlite3.connect(path) as verification:
                self.assertEqual(verification.execute("SELECT value FROM records").fetchall(), [("saved",)])

            failed_connection = None
            with self.assertRaisesRegex(RuntimeError, "expected"):
                with canonical_database.db_session(path) as failed_connection:
                    failed_connection.execute("INSERT INTO records VALUES ('exception rollback')")
                    raise RuntimeError("expected")
            with self.assertRaises(sqlite3.ProgrammingError):
                failed_connection.execute("SELECT 1")
            with sqlite3.connect(path) as verification:
                self.assertEqual(verification.execute("SELECT value FROM records").fetchall(), [("saved",)])

    def test_canonical_schema_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.db"
            canonical_database.initialize(path)
            with sqlite3.connect(path) as connection:
                first_migrations = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            canonical_database.initialize(path)
            with sqlite3.connect(path) as connection:
                migrations = connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
                tables = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'lots'"
                ).fetchone()[0]
            self.assertEqual(migrations, first_migrations)
            self.assertGreater(migrations, 0)
            self.assertEqual(tables, 1)

    def test_canonical_department_schemas_is_a_pure_boundary_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_app = Path(temporary) / "app"
            source = Path(__file__).resolve().parents[1] / "app"
            shutil.copytree(source, copied_app)
            target = copied_app / "persistence" / "department_schemas.py"
            target.write_text(target.read_text(encoding="utf-8") + "\nimport socket\n", encoding="utf-8")
            errors = boundary_errors(copied_app, load_manifest())
        self.assertTrue(
            any(
                "app.persistence.department_schemas" in error
                and "pure module imports forbidden socket" in error
                for error in errors
            )
        )


if __name__ == "__main__":
    unittest.main()
