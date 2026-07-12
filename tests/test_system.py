from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.audit import sanitize
from app.main import app
from app.rag import search_knowledge
from app.reports import process_capability, report_bundle, safe_select


class FabInsightTests(unittest.TestCase):
    def test_dashboard_has_manufacturing_data(self):
        dashboard = report_bundle()
        self.assertGreater(dashboard["overview"]["lots"], 300)
        self.assertGreater(dashboard["overview"]["yield_pct"], 80)
        self.assertTrue(dashboard["equipment"])

    def test_seeded_cvd_drift_is_detectable(self):
        capability = process_capability(process_step="CVD")
        cvd_02 = next(row for row in capability if row["equipment_id"] == "CVD-02")
        peers = [row for row in capability if row["equipment_id"] != "CVD-02"]
        self.assertLess(cvd_02["cpk"], min(row["cpk"] for row in peers))

    def test_rag_returns_cited_source(self):
        results = search_knowledge("CVD 膜厚偏高处置", 3)
        self.assertTrue(results)
        self.assertEqual(results[0]["source"], "CVD_control_plan.md")
        self.assertIn("section", results[0])

    def test_sql_guard_rejects_writes(self):
        with self.assertRaises(ValueError):
            safe_select("DELETE FROM lots")
        with self.assertRaises(ValueError):
            safe_select("SELECT * FROM sqlite_master")

    def test_health_endpoint(self):
        with TestClient(app) as client:
            response = client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")

    def test_monitor_endpoint_is_sanitized(self):
        with TestClient(app) as client:
            response = client.get("/api/monitor/summary?hours=24")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("runs", payload)
            self.assertNotIn("api_key", str(payload).lower())

    def test_model_can_be_switched_without_exposing_key(self):
        with TestClient(app) as client:
            initial = client.get("/api/settings/model")
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.json()["allowed_models"], ["deepseekv4-flash", "deepseekv4-pro"])
            response = client.post("/api/settings/model", json={
                "model": "deepseekv4-pro",
                "api_key": "test-secret-api-key",
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["model"], "deepseekv4-pro")
            self.assertEqual(response.json()["provider_model"], "deepseek-v4-pro")
            self.assertNotIn("test-secret-api-key", response.text)
            client.post("/api/settings/model", json={"model": "deepseekv4-flash"})

    def test_unknown_model_is_rejected(self):
        with TestClient(app) as client:
            response = client.post("/api/settings/model", json={"model": "unknown-model"})
            self.assertEqual(response.status_code, 400)

    def test_full_logging_still_redacts_credentials(self):
        payload = sanitize({
            "DEEPSEEK_API_KEY": "secret-key",
            "headers": {"Authorization": "Bearer secret-token"},
            "input_tokens": 42,
        })
        self.assertEqual(payload["DEEPSEEK_API_KEY"], "<redacted>")
        self.assertEqual(payload["headers"]["Authorization"], "<redacted>")
        self.assertEqual(payload["input_tokens"], 42)


if __name__ == "__main__":
    unittest.main()
