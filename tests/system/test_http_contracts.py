from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from tests.system.support import PROJECT_DIR, isolated_system_environment

isolated_system_environment()

from fastapi.testclient import TestClient

from app.audit import sanitize
from app.config import APP_VERSION
from app.main import app
from app.seed import seed_reference_data

class HttpContractsSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_reference_data()

    def test_health_exposes_runtime_instance_identity(self):
        with TestClient(app) as client:
            payload = client.get("/api/health").json()

        self.assertIn("instance", payload)
        self.assertIn("model_health", payload)
        self.assertTrue(payload["instance"]["id"])
        self.assertTrue(payload["instance"]["root"])
        self.assertTrue(payload["instance"]["source_root"])

    def test_frontend_exposes_personal_knowledge_upload_workflow(self):
        with TestClient(app) as client:
            response = client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.text
        for element_id in (
            "knowledgeSourceTabs",
            "knowledgeUploadDialog",
            "knowledgeUploadFile",
            "knowledgeUploadQueue",
            "personalKnowledgeActions",
            "editPersonalKnowledge",
            "personalKnowledgeMetadataDialog",
            "personalKnowledgeDeleteDialog",
        ):
            self.assertIn(f'id="{element_id}"', page)
        self.assertIn(f"/static/stream_diagnostics.js?v={APP_VERSION}", page)
        self.assertIn(f"/static/stream_buffer.js?v={APP_VERSION}", page)
        self.assertIn(f"/static/stream_markdown.js?v={APP_VERSION}", page)
        self.assertIn(f"/static/source_presenter.js?v={APP_VERSION}", page)
        self.assertIn(f"/static/personal_upload_queue.js?v={APP_VERSION}", page)
        self.assertIn(f"/static/personal_knowledge_metadata.js?v={APP_VERSION}", page)
        self.assertIn(f"/static/personal_job_events.js?v={APP_VERSION}", page)
        self.assertIn(f"/static/thinking_control.js?v={APP_VERSION}", page)
        self.assertIn(f"/static/app.js?v={APP_VERSION}", page)
        self.assertNotIn('id="monitorView"', page)
        self.assertNotIn('id="apiKeyInput"', page)
        styles = (PROJECT_DIR / "app" / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("scrollbar-gutter: stable", styles)
        script = (PROJECT_DIR / "app" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("data-open-knowledge-upload", script)
        self.assertIn("data-personal-chunk", script)
        self.assertIn("renderSourcePanel(messageSources)", script)
        self.assertIn("sourcePresenter.stripSourceAppendix(content)", script)
        self.assertIn("function mergeKnowledgeUploadFiles(files)", script)
        self.assertIn("personal-knowledge-upload-more", script)
        self.assertIn("personalUploadQueue.uploadSequential", script)
        self.assertIn("item.status === 'failed' || item.status === 'invalid'", script)
        self.assertIn("sourcePresenter.replaceReferenceIds(content, sources)", script)
        self.assertIn("method: 'PATCH'", script)
        self.assertIn("personalKnowledgeMetadata.buildPatch", script)
        self.assertIn("refreshRenderedPersonalSourceName(documentId, updated.title)", script)
        self.assertIn("event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229", script)
        self.assertIn("$('#chatForm').requestSubmit()", script)
        self.assertIn("item.status === 'blocked'", script)
        self.assertIn("执行路径受限", script)
        self.assertIn("await finishLiveAnswer(live, result.answer)", script)
        self.assertIn("reportStreamTelemetry(live, result.answer)", script)
        self.assertIn("模型继续生成中", script)
        self.assertIn("insertAdjacentHTML('beforeend', renderMarkdown(patch.stableDelta))", script)
        self.assertNotIn("answer.innerHTML = renderMarkdown(visible)", script)
        self.assertIn("maxChars: live.buffer.complete ? 32 : 24", script)
        self.assertIn("live.caret.className = 'streaming-caret'", script)
        self.assertNotIn("window.clearTimeout(live.renderTimer); live.renderTimer = null;", script)
        self.assertNotIn("item.arguments", script)
        self.assertNotIn("event.arguments", script)
        self.assertNotIn("argumentsText", script)
        self.assertIn(".trace-status-blocked", styles)
        self.assertIn(".source-list[open] summary::before", styles)

    def test_admin_frontend_is_separate_from_user_workspace(self):
        with TestClient(app) as client:
            response = client.get("/admin")
        self.assertEqual(response.status_code, 200)
        for element_id in (
            "adminAuthDialog",
            "runtimeView",
            "userStatusBody",
            "modelsView",
            "publishModelDialog",
        ):
            self.assertIn(f'id="{element_id}"', response.text)
        self.assertIn('<div id="adminWorkspace" class="admin-workspace" hidden>', response.text)
        self.assertIn(f"/static/admin.js?v={APP_VERSION}", response.text)
        self.assertIn(f"/static/model_capabilities.js?v={APP_VERSION}", response.text)
        script = (PROJECT_DIR / "app" / "static" / "admin.js").read_text(encoding="utf-8")
        self.assertIn("/api/admin/overview", script)
        self.assertIn("/api/admin/models", script)
        self.assertIn('<th scope="col">健康</th>', (PROJECT_DIR / "app" / "static" / "admin.html").read_text(encoding="utf-8"))
        self.assertIn('data-label="健康"', script)
        self.assertIn("health-chip", (PROJECT_DIR / "app" / "static" / "admin.css").read_text(encoding="utf-8"))
        self.assertIn("$('#adminWorkspace').hidden = true", script)
        self.assertIn("$('#adminWorkspace').hidden = false", script)
        self.assertIn("run.question_preview", script)
        self.assertIn("run.session_id", script)
        self.assertIn("问题 / Session", response.text)
        self.assertIn('id="publishThinking"', response.text)
        self.assertIn('id="publishNativeMultimodal"', response.text)
        self.assertIn("native_multimodal", script)
        self.assertIn("FabModelCapabilities.enabledEntries(model.capabilities)", script)

    def test_health_endpoint(self):
        with TestClient(app) as client:
            response = client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")
            self.assertEqual(response.json()["reference_data"]["knowledge_chunks"], 68)
            self.assertEqual(response.json()["reference_data"]["historical_cases"], 17)
            self.assertTrue(response.json()["build"]["version"])
            self.assertTrue(response.json()["enterprise"]["simulated"])
            self.assertEqual(response.json()["enterprise"]["virtual_scale"]["lots"], 25_000_000)

    def test_enterprise_context_resolves_request_identity(self):
        headers = {"X-Tenant-ID": "fab-east", "X-User-ID": "engineer-07", "X-Roles": "analyst,process-engineer"}
        with TestClient(app) as client:
            response = client.get("/api/enterprise/context", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["identity"]["tenant_id"], "fab-east")
            self.assertEqual(response.json()["identity"]["user_id"], "engineer-07")
            self.assertEqual(response.json()["knowledge_owner_scope"], "fab-east:engineer-07")
            self.assertEqual(response.json()["identity"]["roles"], ["analyst", "process-engineer"])

            invalid = client.get(
                "/api/enterprise/context",
                headers={"X-Tenant-ID": "invalid tenant", "X-User-ID": "engineer-07"},
            )
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(invalid.json()["error_code"], "INVALID_IDENTITY")

    def test_enterprise_mock_data_is_deterministic_and_cursor_scoped(self):
        headers = {"X-Tenant-ID": "fab-a", "X-User-ID": "analyst"}
        path = "/api/enterprise/data/process-runs?process_step=ETCH&limit=3"
        with TestClient(app) as client:
            first = client.get(path, headers=headers)
            repeated = client.get(path, headers=headers)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()["records"], repeated.json()["records"])
            self.assertTrue(all(item["process_step"] == "ETCH" and item["synthetic"] for item in first.json()["records"]))
            cursor = first.json()["page"]["next_cursor"]
            self.assertTrue(cursor)

            second = client.get(
                "/api/enterprise/data/process-runs",
                headers=headers,
                params={"process_step": "ETCH", "limit": 3, "cursor": cursor},
            )
            self.assertEqual(second.status_code, 200, second.text)
            self.assertFalse(
                {item["run_id"] for item in first.json()["records"]}
                & {item["run_id"] for item in second.json()["records"]}
            )

            cross_tenant = client.get(
                "/api/enterprise/data/process-runs",
                headers={"X-Tenant-ID": "fab-b", "X-User-ID": "analyst"},
                params={"process_step": "ETCH", "limit": 3, "cursor": cursor},
            )
            self.assertEqual(cross_tenant.status_code, 400)
            self.assertEqual(cross_tenant.json()["error_code"], "CURSOR_SCOPE_MISMATCH")

            midpoint = len(cursor) // 2
            replacement = "A" if cursor[midpoint] != "A" else "B"
            tampered = f"{cursor[:midpoint]}{replacement}{cursor[midpoint + 1:]}"
            invalid = client.get(
                "/api/enterprise/data/process-runs",
                headers=headers,
                params={"process_step": "ETCH", "limit": 3, "cursor": tampered},
            )
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(invalid.json()["error_code"], "INVALID_CURSOR")

    def test_enterprise_summary_is_projected_deterministic_and_tenant_scoped(self):
        end = date.today()
        start = end - timedelta(days=6)
        params = {"start": start.isoformat(), "end": end.isoformat(), "process_step": "CMP"}
        tenant_a = {"X-Tenant-ID": "fab-summary-a", "X-User-ID": "analyst"}
        tenant_b = {"X-Tenant-ID": "fab-summary-b", "X-User-ID": "analyst"}
        with TestClient(app) as client:
            first = client.get("/api/enterprise/data/summary", headers=tenant_a, params=params)
            repeated = client.get("/api/enterprise/data/summary", headers=tenant_a, params=params)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json(), repeated.json())
            payload = first.json()
            self.assertTrue(payload["simulated"])
            self.assertFalse(payload["aggregation"]["exact"])
            self.assertEqual(payload["aggregation"]["semantics"], "deterministic_projection")
            self.assertEqual(payload["query"]["filters"]["process_step"], "CMP")
            self.assertGreater(payload["totals"]["lots"], 0)
            self.assertGreater(payload["totals"]["process_runs"], payload["totals"]["lots"])
            self.assertGreater(payload["totals"]["sensor_events"], payload["totals"]["process_runs"])
            self.assertEqual(len(payload["equipment"]), 5)
            self.assertEqual(
                [item["health_score"] for item in payload["equipment"]],
                sorted(item["health_score"] for item in payload["equipment"]),
            )
            self.assertEqual(payload["lineage"]["classification"], "synthetic_non_production")

            other_tenant = client.get("/api/enterprise/data/summary", headers=tenant_b, params=params)
            self.assertEqual(other_tenant.status_code, 200)
            for field in ("lots", "wafers", "process_runs", "sensor_events"):
                self.assertEqual(other_tenant.json()["totals"][field], payload["totals"][field])
            self.assertNotEqual(other_tenant.json()["query"]["query_id"], payload["query"]["query_id"])
            self.assertNotEqual(other_tenant.json()["kpis"], payload["kpis"])

            equipment = client.get(
                "/api/enterprise/data/summary",
                headers=tenant_a,
                params={**params, "equipment_id": "CMP-03"},
            )
            self.assertEqual(equipment.status_code, 200)
            self.assertEqual([item["equipment_id"] for item in equipment.json()["equipment"]], ["CMP-03"])
            self.assertLess(equipment.json()["totals"]["lots"], payload["totals"]["lots"])

            invalid = client.get(
                "/api/enterprise/data/summary",
                headers=tenant_a,
                params={"start": end.isoformat(), "end": start.isoformat()},
            )
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(invalid.json()["error_code"], "INVALID_DATE_RANGE")

    def test_api_errors_include_correlation_id_and_retry_metadata(self):
        request_id = "req-test-correlation-001"
        with TestClient(app) as client:
            response = client.get("/api/sessions/missing-session", headers={"X-Request-ID": request_id})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.headers["x-request-id"], request_id)
            self.assertEqual(response.json()["request_id"], request_id)
            self.assertEqual(response.json()["error_code"], "NOT_FOUND")
            self.assertFalse(response.json()["retryable"])

            invalid = client.post("/api/chat/stream", json={"message": "x"})
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(invalid.json()["error_code"], "VALIDATION_ERROR")
            self.assertTrue(invalid.json()["request_id"])

    def test_unexpected_500_is_structured_without_exposing_traceback(self):
        request_id = "req-internal-error-001"
        with patch("app.main.report_bundle", side_effect=RuntimeError("database secret detail")), TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/reports/dashboard", headers={"X-Request-ID": request_id})
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.headers["x-request-id"], request_id)
            self.assertEqual(response.json()["error_code"], "INTERNAL_ERROR")
            self.assertEqual(response.json()["request_id"], request_id)
            self.assertTrue(response.json()["retryable"])
            self.assertNotIn("database secret detail", response.text)

    def test_monitor_endpoint_is_sanitized(self):
        with patch.dict(os.environ, {"FAB_ADMIN_API_TOKEN": "monitor-admin-token"}), TestClient(app) as client:
            self.assertEqual(client.get("/api/monitor/summary?hours=24").status_code, 401)
            response = client.get(
                "/api/monitor/summary?hours=24",
                headers={"Authorization": "Bearer monitor-admin-token"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("runs", payload)
            self.assertNotIn("api_key", str(payload).lower())

class HttpContractTests(unittest.TestCase):
    """Small endpoint contracts kept separate from broad system workflow tests."""

    def test_version_contract_exposes_current_build_identity(self):
        with TestClient(app) as client:
            response = client.get("/api/version")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], APP_VERSION)
        self.assertIn("git_commit", response.json())
        self.assertIn("instance_id", response.json())

    def test_enterprise_manifest_is_available_to_the_current_principal(self):
        with TestClient(app) as client:
            response = client.get("/api/enterprise/data/manifest")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("provider", response.json())
        self.assertIn("entities", response.json())

    def test_capability_contract_validates_scope_and_returns_rows(self):
        with TestClient(app) as client:
            valid = client.get("/api/reports/capability", params={"process_step": "CVD"})
            invalid = client.get("/api/reports/capability", params={"process_step": "UNKNOWN"})
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertTrue(valid.json())
        self.assertTrue(all(row["equipment_id"].startswith("CVD-") for row in valid.json()))
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["error_code"], "VALIDATION_ERROR")

    def test_rag_search_contract_covers_valid_and_invalid_query_boundaries(self):
        with TestClient(app) as client:
            valid = client.get("/api/rag/search", params={"q": "CVD particle", "limit": 2})
            too_short = client.get("/api/rag/search", params={"q": "x"})
            too_many = client.get("/api/rag/search", params={"q": "CVD", "limit": 11})
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["query"], "CVD particle")
        self.assertLessEqual(valid.json()["count"], 2)
        self.assertEqual(too_short.status_code, 422)
        self.assertEqual(too_many.status_code, 422)

    def test_monitor_events_requires_admin_and_returns_sanitized_events(self):
        event = sanitize({"event": "quality_gate", "api_key": "must-not-leak", "safe": "visible"})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FAB_ADMIN_API_TOKEN", None)
            with TestClient(app) as client:
                unavailable = client.get("/api/monitor/events")
        with patch.dict(os.environ, {"FAB_ADMIN_API_TOKEN": "quality-gate-token"}):
            with patch("app.main.read_events", return_value=[event]):
                with TestClient(app) as client:
                    unauthorized = client.get("/api/monitor/events", headers={"Authorization": "Bearer wrong"})
                    authorized = client.get(
                        "/api/monitor/events", params={"limit": 1}, headers={"Authorization": "Bearer quality-gate-token"}
                    )
                    invalid_limit = client.get(
                        "/api/monitor/events", params={"limit": 0}, headers={"Authorization": "Bearer quality-gate-token"}
                    )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json()[0]["api_key"], "<redacted>")
        self.assertEqual(authorized.json()[0]["safe"], "visible")
        self.assertEqual(invalid_limit.status_code, 422)

if __name__ == "__main__":
    unittest.main()
