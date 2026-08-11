import unittest

from tests.system.support import isolated_system_environment
isolated_system_environment()

from app.database import db_session, ensure_department_databases
from app.model_registry import publish_model, save_model_compatibility_report, set_model_status, update_model_capabilities


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

    def args(self):
        return (self.model_id, "Publication Unit", "openai-compatible", "unit-model", "https://unit.test/v1", {"streaming": True, "tool_calls": True}, "test")

    def test_publish_and_republish_do_not_require_a_report(self):
        published = publish_model(*self.args())
        self.assertEqual(published["compatibility"]["status"], "unverified")
        set_model_status(self.model_id, "retired")
        self.assertEqual(set_model_status(self.model_id, "published")["status"], "published")

    def test_successful_report_and_checked_at_persist(self):
        report = {"status": "passed", "checked_at": "2026-08-11T00:00:00+00:00", "checks": [{"name": "context"}]}
        publish_model(*self.args()); save_model_compatibility_report(self.model_id, report)
        with db_session() as connection:
            row = connection.execute("SELECT compatibility_json, compatibility_checked_at FROM agent.model_catalog WHERE model_id=?", (self.model_id,)).fetchone()
        self.assertIn('"status":"passed"', row[0]); self.assertEqual(row[1], report["checked_at"])

    def test_report_does_not_change_status_or_capabilities(self):
        publish_model(*self.args()); set_model_status(self.model_id, "retired")
        saved = save_model_compatibility_report(self.model_id, {"status": "failed", "summary": "bounded"})
        self.assertEqual(saved["status"], "retired")
        self.assertEqual(saved["capabilities"]["thinking"], False)
        self.assertEqual(saved["compatibility"]["status"], "failed")

    def test_capability_update_preserves_status_and_invalidates_report(self):
        publish_model(*self.args()); set_model_status(self.model_id, "retired")
        updated = update_model_capabilities(self.model_id, {"streaming": True, "tool_calls": True, "thinking": True, "native_multimodal": False})
        self.assertEqual(updated["status"], "retired")
        self.assertTrue(updated["capabilities"]["thinking"])
        self.assertEqual(updated["compatibility"]["status"], "unverified")
        self.assertIsNone(updated["compatibility_checked_at"])
        with self.assertRaisesRegex(ValueError, "模型不存在"):
            update_model_capabilities("missing-model", {"streaming": True, "tool_calls": True, "thinking": False, "native_multimodal": False})
