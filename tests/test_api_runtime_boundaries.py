import asyncio
import unittest
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError

from app import main
from app.api import runtime_dependencies
from app.api.application import (
    ApplicationDependencies,
    create_application,
    lifespan_for,
)
from app.api.errors import ErrorDependencies, handlers
from app.api import schemas
from app.api.schemas import ChatRequest, StreamTelemetryRequest
from app.identity import PrincipalContextMiddleware
from app.observability import RequestAuditMiddleware


class ApiRuntimeBoundaryTests(unittest.TestCase):
    def test_main_publishes_runtime_dependencies_by_identity(self):
        for name, dependency in runtime_dependencies.RUNTIME_DEPENDENCIES.items():
            with self.subTest(name=name):
                self.assertIs(getattr(main, name), dependency)

    def test_main_composition_keeps_router_exports_and_no_domain_implementations(self):
        self.assertIs(main.dashboard, main._report_routes.exports["dashboard"])
        self.assertIs(main.chat, main._chat_routes.exports["chat"])
        self.assertIs(
            main.monitor_events, main._monitor_routes.exports["monitor_events"]
        )
        source = Path(main.__file__).read_text(encoding="utf-8")
        self.assertGreaterEqual(len(source.splitlines()), 150)
        self.assertLessEqual(len(source.splitlines()), 250)
        self.assertNotIn('@app.post("/api/chat")', source)
        self.assertNotIn("async def event_stream", source)
        self.assertFalse(hasattr(main, "_routes"))

    def test_main_reexports_schema_objects(self):
        for name in (
            "ChatMessage",
            "ChatRequest",
            "StreamTelemetryRequest",
            "ModelConfigRequest",
            "ModelCapabilitiesRequest",
            "AdminModelPublishRequest",
            "AdminModelStatusRequest",
            "AdminModelCapabilitiesRequest",
            "SessionUpdateRequest",
            "BulkSessionDeleteRequest",
            "PersonalSearchPreviewRequest",
        ):
            self.assertIs(getattr(main, name), getattr(schemas, name))

    def test_authentication_wrapper_uses_current_main_dependencies(self):
        settings = SimpleNamespace(
            personal_knowledge_api_token="secret", admin_api_token="admin"
        )
        principal = SimpleNamespace(knowledge_owner_id="owner")
        with (
            patch("app.main.get_settings", return_value=settings),
            patch("app.main.current_principal", return_value=principal),
        ):
            self.assertEqual(main.current_personal_user("Bearer secret"), "owner")
            self.assertEqual(main.current_admin("Bearer admin"), "administrator")

    def test_error_handlers_preserve_headers_and_payload(self):
        async def run():
            http_handler, validation_handler, _ = handlers(
                ErrorDependencies(lambda: "request-1", lambda *args, **kwargs: None)
            )
            response = await http_handler(
                None,
                HTTPException(
                    401, detail="denied", headers={"WWW-Authenticate": "Bearer"}
                ),
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")
            self.assertIn(b'"request_id":"request-1"', response.body)
            validation = RequestValidationError(
                [
                    {
                        "type": "missing",
                        "loc": ("body", "name"),
                        "msg": "required",
                        "input": {},
                    }
                ]
            )
            response = await validation_handler(None, validation)
            self.assertIn(b'"fields":["name"]', response.body)

        asyncio.run(run())

    def test_lifespan_order_and_personal_workers(self):
        calls = []

        class Connection:
            def execute(self, query):
                calls.append(query)
                if "DISTINCT" in query:
                    return Cursor([("CVD",)])
                if "EXISTS" in query:
                    return Cursor([(1,)])
                if "MAX" in query:
                    return Cursor([(18,)])
                return Cursor([(1,)])

        class Cursor(list):
            def fetchone(self):
                return self[0]

        @contextmanager
        def session():
            yield Connection()

        async def to_thread(worker, *args):
            calls.append((worker.__name__, args))

        def regular(*args):
            pass

        def deleting(*args):
            pass

        deps = ApplicationDependencies(
            ensure_department_databases=lambda: calls.append("departments"),
            recover_interrupted_executions=lambda: calls.append("recovery"),
            ensure_model_catalog=lambda: calls.append("catalog"),
            db_session=session,
            manufacturing_steps=("CVD",),
            generate_database=lambda: calls.append("generate"),
            seed_reference_data=lambda: calls.append("seed"),
            pending_personal_jobs=lambda: [
                ("doc-1", "owner", "job-1", "indexing"),
                ("doc-2", "owner", "job-2", "deleting"),
            ],
            process_personal_document=regular,
            process_personal_document_deletion=deleting,
            to_thread=to_thread,
        )

        async def run():
            async with lifespan_for(deps)(None):
                calls.append("yield")

        asyncio.run(run())
        self.assertEqual(calls[:3], ["departments", "recovery", "catalog"])
        self.assertNotIn("generate", calls)
        self.assertNotIn("seed", calls)
        self.assertIn(("regular", ("doc-1", "owner", "job-1")), calls)
        self.assertIn(("deleting", ("doc-2", "owner", "job-2")), calls)

    def test_application_keeps_middleware_and_static_configuration(self):
        @asynccontextmanager
        async def test_lifespan(_):
            yield

        app = create_application(
            lifespan=test_lifespan,
            project_dir=main.PROJECT_DIR,
            principal_context_middleware=PrincipalContextMiddleware,
            request_audit_middleware=RequestAuditMiddleware,
        )
        self.assertEqual(app.title, "Fab Insight Agent")
        self.assertIs(app.router.lifespan_context, test_lifespan)
        self.assertEqual(
            [item.cls for item in app.user_middleware],
            [RequestAuditMiddleware, PrincipalContextMiddleware],
        )
        self.assertTrue(
            any(
                route.name == "static" and route.path == "/static"
                for route in app.routes
            )
        )
