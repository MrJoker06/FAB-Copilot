from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import audit, observability, runtime_status
from app.identity import Principal
from app.telemetry import audit as canonical_audit
from app.telemetry import http as canonical_http
from app.telemetry import runtime_status as canonical_runtime_status


class TelemetryModuleBoundaryTests(unittest.TestCase):
    def test_legacy_facades_share_public_and_private_telemetry_state(self):
        self.assertIs(audit.emit, canonical_audit.emit)
        self.assertIs(audit._request_id, canonical_audit._request_id)
        self.assertIs(audit._lock, canonical_audit._lock)
        self.assertIs(audit._logger, canonical_audit._logger)
        self.assertIs(observability.RequestAuditMiddleware, canonical_http.RequestAuditMiddleware)
        self.assertIs(runtime_status._lock, canonical_runtime_status._lock)
        self.assertIs(runtime_status._users, canonical_runtime_status._users)
        self.assertIs(runtime_status.begin_agent_run, canonical_runtime_status.begin_agent_run)

    def test_request_contextvar_restores_across_old_and_canonical_paths(self):
        self.assertIsNone(audit.current_request_id())
        old_token = audit.set_request_id("legacy-request")
        try:
            self.assertEqual(canonical_audit.current_request_id(), "legacy-request")
            canonical_token = canonical_audit.set_request_id("canonical-request")
            try:
                self.assertEqual(audit.current_request_id(), "canonical-request")
            finally:
                audit.reset_request_id(canonical_token)
            self.assertEqual(canonical_audit.current_request_id(), "legacy-request")
        finally:
            canonical_audit.reset_request_id(old_token)
        self.assertIsNone(audit.current_request_id())

    def test_import_orders_do_not_duplicate_the_shared_audit_handler(self):
        orders = {
            "legacy_first": "import app.audit; import app.observability; import app.runtime_status; import app.telemetry.audit as audit; print(len(audit._logger.handlers))",
            "canonical_first": "import app.telemetry.audit as audit; import app.telemetry.http; import app.telemetry.runtime_status; import app.audit; import app.observability; import app.runtime_status; print(len(audit._logger.handlers))",
        }
        for name, source in orders.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                environment = {
                    **os.environ,
                    "AGENT_LOG_PATH": f"{directory}/events.jsonl",
                    "AGENT_RUN_LOG_DIR": f"{directory}/runs",
                }
                result = subprocess.run(
                    [sys.executable, "-c", source], capture_output=True,
                    text=True, check=False, env=environment,
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "1")

    def test_runtime_state_is_shared_between_legacy_and_canonical_paths(self):
        principal = Principal("tenant-test", "user-test")
        with patch.object(canonical_runtime_status, "_users", {}):
            runtime_status.begin_agent_run(principal, "session-1", "  inspect   chamber  ", "demo")
            self.assertEqual(canonical_runtime_status.runtime_users()[0]["active_runs"], 1)
            canonical_runtime_status.finish_agent_run(principal, "success", "run-1")
            row = runtime_status.runtime_users()[0]
        self.assertEqual((row["active_runs"], row["status"], row["last_run_id"]), (0, "idle", "run-1"))

    def test_http_middleware_resets_request_id_for_success_error_and_cancellation(self):
        async def invoke(app, events):
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                messages.append(message)

            outer_token = canonical_audit.set_request_id("outer-request")
            try:
                with (
                    patch.object(canonical_http, "get_settings", return_value=SimpleNamespace(enterprise_default_tenant_id="default", enterprise_default_user_id="user")),
                    patch.object(canonical_http, "emit") as emit,
                ):
                    try:
                        await canonical_http.RequestAuditMiddleware(app)(
                            {"type": "http", "path": "/api/test", "method": "GET", "headers": []}, receive, send
                        )
                    finally:
                        events[:] = [call.args[0] for call in emit.call_args_list]
                        self.assertEqual(canonical_audit.current_request_id(), "outer-request")
            finally:
                canonical_audit.reset_request_id(outer_token)
            self.assertIsNone(canonical_audit.current_request_id())
            return messages

        async def success(scope, receive, send):
            self.assertTrue(canonical_audit.current_request_id().startswith("req-"))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        events = []
        messages = asyncio.run(invoke(success, events))
        self.assertEqual(messages[0]["headers"][-1][0], b"x-request-id")
        self.assertEqual(events, ["api_request_started", "api_request_finished"])

        async def failing(scope, receive, send):
            self.assertTrue(canonical_audit.current_request_id().startswith("req-"))
            raise RuntimeError("expected")

        events = []
        messages = asyncio.run(invoke(failing, events))
        self.assertEqual(messages[0]["status"], 500)
        self.assertEqual(events, ["api_request_started", "api_exception", "api_request_finished"])

        async def cancelled(scope, receive, send):
            self.assertTrue(canonical_audit.current_request_id().startswith("req-"))
            raise asyncio.CancelledError()

        events = []
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(invoke(cancelled, events))
        self.assertEqual(events, ["api_request_started"])


if __name__ == "__main__":
    unittest.main()
