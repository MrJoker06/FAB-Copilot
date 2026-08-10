import unittest

from tests.system.support import isolated_system_environment
isolated_system_environment()

from app.database import db_session, ensure_department_databases
from app.model_registry import publish_model, set_model_status


class ModelPublicationTests(unittest.TestCase):
    def setUp(self):
        ensure_department_databases()
        self.model_id = "publication-unit-model"
        with db_session() as connection:
            connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (self.model_id,))
            connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (self.model_id,))
            connection.commit()

    def tearDown(self):
        with db_session() as connection:
            connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (self.model_id,))
            connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (self.model_id,))
            connection.commit()

    def args(self, report=None):
        return (self.model_id, "Publication Unit", "openai-compatible", "unit-model", "https://unit.test/v1", {"streaming": True, "tool_calls": True}, "test", report)

    def test_registry_requires_passing_report_for_publish_and_republish(self):
        with self.assertRaises(ValueError): publish_model(*self.args())
        report = {"status": "passed", "checked_at": "2026-08-11T00:00:00+00:00", "checks": []}
        publish_model(*self.args(report)); set_model_status(self.model_id, "retired")
        with self.assertRaises(ValueError): set_model_status(self.model_id, "published")
        with db_session() as connection:
            self.assertEqual(connection.execute("SELECT status FROM agent.model_catalog WHERE model_id=?", (self.model_id,)).fetchone()[0], "retired")

    def test_successful_report_and_checked_at_persist(self):
        report = {"status": "passed", "checked_at": "2026-08-11T00:00:00+00:00", "checks": [{"name": "context"}]}
        publish_model(*self.args(report))
        with db_session() as connection:
            row = connection.execute("SELECT compatibility_json, compatibility_checked_at FROM agent.model_catalog WHERE model_id=?", (self.model_id,)).fetchone()
        self.assertIn('"status":"passed"', row[0]); self.assertEqual(row[1], report["checked_at"])

    def test_failed_republish_keeps_retired_status_and_previous_report(self):
        report = {"status": "passed", "checked_at": "old", "checks": []}
        publish_model(*self.args(report)); set_model_status(self.model_id, "retired")
        with self.assertRaises(ValueError): set_model_status(self.model_id, "published", {"status": "failed"})
        with db_session() as connection:
            row = connection.execute("SELECT status, compatibility_json FROM agent.model_catalog WHERE model_id=?", (self.model_id,)).fetchone()
        self.assertEqual(row[0], "retired"); self.assertIn('"checked_at":"old"', row[1])
