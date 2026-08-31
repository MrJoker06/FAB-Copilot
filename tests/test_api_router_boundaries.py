from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.routing import APIRoute

import app.main as main
from app.api.routers import (
    admin,
    enterprise,
    knowledge,
    models,
    monitor,
    reports,
    sessions,
    system,
)


class _Connection:
    def __init__(self, row):
        self.row = row

    def execute(self, *_):
        return self

    def fetchone(self):
        return self.row


class _Session:
    def __init__(self, row):
        self.connection = _Connection(row)

    def __enter__(self):
        return self.connection

    def __exit__(self, *_):
        return False


class ApiRouterBoundaryTests(unittest.TestCase):
    def test_domain_modules_and_main_handler_aliases_are_registered(self):
        modules = (
            system,
            enterprise,
            reports,
            models,
            admin,
            knowledge,
            sessions,
            monitor,
        )
        self.assertTrue(all(hasattr(module, "create_router") for module in modules))
        routes = [route for route in main.app.routes if isinstance(route, APIRoute)]
        self.assertEqual(
            len({(route.path, tuple(sorted(route.methods or ()))) for route in routes}),
            len(routes),
        )
        self.assertIs(
            main.dashboard,
            next(
                route.endpoint
                for route in routes
                if route.path == "/api/reports/dashboard"
            ),
        )
        self.assertIs(
            main.personal_knowledge_job_events,
            next(
                route.endpoint
                for route in routes
                if route.path == "/api/knowledge/personal/jobs/events"
            ),
        )
        expected_modules = {
            "/api/health": "app.api.routers.system",
            "/api/enterprise/context": "app.api.routers.enterprise",
            "/api/reports/dashboard": "app.api.routers.reports",
            "/api/settings/model": "app.api.routers.models",
            "/api/admin/overview": "app.api.routers.admin",
            "/api/knowledge/documents": "app.api.routers.knowledge",
            "/api/sessions": "app.api.routers.sessions",
            "/api/monitor/summary": "app.api.routers.monitor",
        }
        for path, module_name in expected_modules.items():
            endpoint = next(route.endpoint for route in routes if route.path == path)
            self.assertEqual(endpoint.__module__, module_name)

        expected_exports = {
            "_system_routes": {
                "render_versioned_page",
                "index",
                "admin_index",
                "health",
                "version",
            },
            "_enterprise_routes": {
                "enterprise_context",
                "_enterprise_page",
                "enterprise_manifest",
                "enterprise_summary",
                "enterprise_lots",
                "enterprise_process_runs",
                "enterprise_sensor_events",
            },
            "_model_routes": {"get_model_config", "set_model_config"},
            "_admin_routes": {
                "_compatibility_failure_report",
                "admin_overview",
                "admin_models",
                "admin_publish_model",
                "admin_update_model_status",
                "admin_update_model_capabilities",
                "admin_check_model_compatibility",
            },
            "_report_routes": {"dashboard", "capability"},
            "_knowledge_routes": {
                "knowledge_documents",
                "knowledge_document",
                "upload_personal_knowledge_document",
                "personal_knowledge_job_events",
                "personal_knowledge_job",
                "personal_knowledge_documents",
                "personal_knowledge_document",
                "personal_knowledge_document_content",
                "download_personal_knowledge_document",
                "patch_personal_knowledge_document",
                "retry_personal_knowledge_document",
                "delete_personal_knowledge_document",
                "personal_knowledge_search_preview",
                "personal_knowledge_chunk",
                "historical_cases",
                "historical_case",
                "rag_search",
            },
            "_session_routes": {
                "start_session",
                "session_list",
                "update_session",
                "delete_session",
                "restore_archived_session",
                "permanently_delete_session",
                "bulk_delete_sessions",
                "read_session",
                "read_agent_run_audit",
            },
            "_monitor_routes": {
                "record_stream_telemetry",
                "monitor_summary",
                "monitor_events",
            },
        }
        for bundle_name, expected_keys in expected_exports.items():
            self.assertEqual(set(getattr(main, bundle_name).exports), expected_keys)
        paths = [route.path for route in routes]
        self.assertLess(
            paths.index("/api/knowledge/personal/jobs/events"),
            paths.index("/api/knowledge/jobs/{job_id}"),
        )
        self.assertLess(
            paths.index("/api/sessions/bulk-delete"),
            paths.index("/api/sessions/{session_id}"),
        )

    def test_runtime_patches_flow_through_extracted_handlers(self):
        with patch.object(
            main, "report_bundle", return_value={"ok": True}
        ) as report_bundle:
            self.assertEqual(main.dashboard(), {"ok": True})
            report_bundle.assert_called_once_with(None, None)
        with patch.object(
            main, "read_events", return_value=[{"event": "first"}, {"event": "last"}]
        ):
            self.assertEqual(
                main.monitor_events("admin", 2), [{"event": "last"}, {"event": "first"}]
            )

    def test_admin_compatibility_and_knowledge_sse_read_live_main_dependencies(self):
        row = {
            "provider": "openai",
            "provider_model": "model",
            "base_url": "https://example.test",
            "capabilities_json": "{}",
        }
        settings = Mock(model_connection=Mock(api_key="key"))
        with (
            patch.object(main, "db_session", return_value=_Session(row)),
            patch.object(main, "get_settings", return_value=settings),
            patch.object(
                main,
                "check_model_compatibility",
                new=AsyncMock(return_value={"checks": []}),
            ) as compatibility,
            patch.object(
                main,
                "save_model_compatibility_report",
                return_value={"model_id": "model"},
            ),
            patch.object(main, "emit"),
        ):
            asyncio.run(main.admin_check_model_compatibility("model", "admin"))
            compatibility.assert_awaited_once()

        request = Mock(is_disconnected=AsyncMock(return_value=False))
        snapshot = [{"job_id": "job", "updated_at": "now", "status": "ready"}]
        with patch.object(
            main, "read_personal_job_snapshots", new=AsyncMock(return_value=snapshot)
        ):
            response = asyncio.run(main.personal_knowledge_job_events(request, "user"))
            event = asyncio.run(anext(response.body_iterator))
        self.assertIn("job", event)
