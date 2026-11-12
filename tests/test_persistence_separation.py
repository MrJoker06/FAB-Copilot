"""Real storage separation and delivery checks, without production connections."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from app.persistence import database
from app.demo_data import database as demo_database
from app.demo_data.seed import generate_database

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_module_release  # noqa: E402
import module_release  # noqa: E402
from scripts.check_module_boundaries import boundary_errors, load_manifest  # noqa: E402


def storage_environment(root: Path) -> dict[str, str]:
    return {
        "FAB_PROJECT_ENV_FILE": str(root / "missing-project.env"),
        "FAB_WORKSPACE_ENV_FILE": str(root / "missing-workspace.env"),
        "FAB_DATABASE_PATH": str(root / "legacy.db"),
        "FAB_DATABASE_DIR": str(root),
        "FAB_MANUFACTURING_DATABASE_PATH": str(root / "manufacturing.db"),
        "FAB_EQUIPMENT_DATABASE_PATH": str(root / "equipment.db"),
        "FAB_QUALITY_DATABASE_PATH": str(root / "quality.db"),
        "FAB_KNOWLEDGE_DATABASE_PATH": str(root / "knowledge.db"),
        "FAB_AGENT_DATABASE_PATH": str(root / "agent.db"),
    }


class PersistenceSeparationTests(unittest.TestCase):
    def test_storage_dependency_guard_rejects_demo_import_before_execution(self):
        with tempfile.TemporaryDirectory() as raw:
            app = Path(raw) / "app"
            shutil.copytree(
                ROOT / "app", app, ignore=shutil.ignore_patterns("__pycache__")
            )
            module = app / "persistence" / "database.py"
            module.write_bytes(
                module.read_bytes()
                + b"\nfrom app.demo_data import database as fixtures\n"
            )
            errors = boundary_errors(app, load_manifest())
            self.assertTrue(
                any(
                    "app.persistence.database" in error and "app.demo_data" in error
                    for error in errors
                ),
                errors,
            )
            pure = app / "intent_runtime" / "contracts.py"
            pure.write_bytes(
                pure.read_bytes() + b"\nfrom app.persistence import connection\n"
            )
            errors = boundary_errors(app, load_manifest())
            self.assertTrue(
                any(
                    "app.intent_runtime.contracts" in error
                    and "pure module imports forbidden app.persistence.connection"
                    in error
                    for error in errors
                ),
                errors,
            )

    def test_application_initialization_creates_only_owned_state_stores(self):
        with (
            tempfile.TemporaryDirectory() as raw,
            patch.dict(os.environ, storage_environment(Path(raw))),
        ):
            root = Path(raw)
            database.initialize()
            self.assertEqual(
                {p.name for p in root.glob("*.db")}, {"agent.db", "knowledge.db"}
            )
            with database.db_session() as connection:
                names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_temp_master WHERE type='view'"
                    )
                }
                self.assertTrue(
                    {"chat_sessions", "agent_runs", "knowledge_chunks", "model_catalog"}
                    <= names
                )
                self.assertFalse(
                    {"lots", "process_runs", "simulation_metadata", "defect_types"}
                    & names
                )
                for table in ("lots", "simulation_metadata"):
                    with (
                        self.subTest(table=table),
                        self.assertRaises(sqlite3.OperationalError),
                    ):
                        connection.execute(f"SELECT * FROM {table}")
                with self.assertRaises(KeyError):
                    database.writable_table("lots")

    def test_application_state_commits_rolls_back_and_reinitializes_without_business_writes(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as raw,
            patch.dict(os.environ, storage_environment(Path(raw))),
        ):
            root = Path(raw)
            business = root / "manufacturing.db"
            with closing(sqlite3.connect(business)) as connection:
                connection.execute("CREATE TABLE company_sentinel(value TEXT)")
                connection.execute("INSERT INTO company_sentinel VALUES ('untouched')")
                connection.commit()
            before = business.read_bytes()
            database.initialize()
            session_table = database.writable_table("chat_sessions")
            with database.db_session() as connection:
                connection.execute(
                    f"INSERT INTO {session_table}(session_id,title,created_at,updated_at) VALUES ('saved','retained','2026-01-01','2026-01-01')"
                )
                connection.commit()
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                with database.db_session() as connection:
                    connection.execute(
                        f"UPDATE {session_table} SET title='rolled back'"
                    )
                    raise RuntimeError("cancelled")
            database.initialize()
            with database.db_session() as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT title FROM chat_sessions WHERE session_id='saved'"
                    ).fetchone()[0],
                    "retained",
                )
            self.assertEqual(business.read_bytes(), before)
            self.assertFalse((root / "equipment.db").exists())
            self.assertFalse((root / "quality.db").exists())

    def test_explicit_single_application_database_does_not_include_demo_schema(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "application.db"
            database.initialize(path)
            database.initialize(path)
            with database.db_session(path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertIn("personal_knowledge_documents", tables)
                self.assertIn("agent_plan_steps", tables)
                self.assertNotIn("lots", tables)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM model_catalog").fetchone()[
                        0
                    ],
                    0,
                )

    def test_demo_layout_and_generation_remain_explicit(self):
        with (
            tempfile.TemporaryDirectory() as raw,
            patch.dict(os.environ, storage_environment(Path(raw))),
        ):
            root = Path(raw)
            database.initialize()
            self.assertFalse((root / "manufacturing.db").exists())
            demo_database.initialize()
            with demo_database.db_session() as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 0
                )
                self.assertGreater(
                    connection.execute("SELECT COUNT(*) FROM defect_types").fetchone()[
                        0
                    ],
                    0,
                )
            generate_database(days=1, seed=7, end_date="2026-12-25")
            with demo_database.db_session() as connection:
                self.assertGreater(
                    connection.execute("SELECT COUNT(*) FROM lots").fetchone()[0], 0
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT classification FROM simulation_metadata"
                    ).fetchone()[0],
                    "synthetic_non_production",
                )

    def test_real_delivery_runs_without_demo_package_or_repository_imports(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            delivery, virtual = root / "delivery", root / "venv"
            module_release.build(delivery, build_id="application-storage-separation")
            release, members = install_module_release.read(
                delivery, ["application_storage"]
            )
            selected = release["profiles"]["application_storage"]["source_files"]
            self.assertEqual(len(selected), 10)
            self.assertFalse(
                any(path.startswith("app/demo_data/") for path in selected)
            )
            venv.EnvBuilder(with_pip=False).create(virtual)
            python = virtual / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            purelib = Path(
                subprocess.check_output(
                    [
                        str(python),
                        "-I",
                        "-c",
                        "import sysconfig;print(sysconfig.get_paths()['purelib'])",
                    ],
                    text=True,
                ).strip()
            )
            install_module_release.install(
                delivery, purelib, ["application_storage"], python=python
            )
            script = """
import json, sqlite3, sys
from pathlib import Path
from contextlib import closing
from app.persistence import database
database.initialize()
with database.db_session() as connection:
    connection.execute("INSERT INTO agent.chat_sessions(session_id,title,created_at,updated_at) VALUES ('isolated','outside','2026-01-01','2026-01-01')")
    connection.commit()
database.initialize()
with database.db_session() as connection:
    assert connection.execute("SELECT title FROM chat_sessions").fetchone()[0] == 'outside'
    try:
        connection.execute('SELECT * FROM lots')
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError('business data unexpectedly accessible')
assert not any(name == 'app.demo_data' or name.startswith('app.demo_data.') for name in sys.modules)
assert not (Path(database.__file__).parents[1] / 'demo_data').exists()
print(json.dumps({'module': str(Path(database.__file__).resolve()), 'status': 'PASS'}))
"""
            environment = {**os.environ, **storage_environment(root / "state")}
            result = subprocess.run(
                [str(python), "-I", "-X", "utf8", "-c", script],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "PASS")
            self.assertTrue(Path(payload["module"]).is_relative_to(purelib))
            self.assertEqual(
                {p.name for p in (root / "state").glob("*.db")},
                {"knowledge.db", "agent.db"},
            )


if __name__ == "__main__":
    unittest.main()
