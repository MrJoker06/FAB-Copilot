from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.telemetry import audit, http as observability, runtime_status
from app.core.identity import Principal


class TelemetryModuleBoundaryTests(unittest.TestCase):
    def test_canonical_telemetry_exports_have_owners_and_removed_roots(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app"
        for name in ("audit", "observability", "runtime_status"):
            self.assertFalse((root / f"{name}.py").exists())
        owners = (
            (audit.emit, "app.telemetry.audit"), (observability.RequestAuditMiddleware, "app.telemetry.http"),
            (runtime_status.begin_agent_run, "app.telemetry.runtime_status"),
        )
        for value, owner in owners:
            self.assertEqual(value.__module__, owner)

    def test_request_contextvar_restores_nested_tokens(self):
        self.assertIsNone(audit.current_request_id())
        old_token = audit.set_request_id("legacy-request")
        try:
            self.assertEqual(audit.current_request_id(), "legacy-request")
            canonical_token = audit.set_request_id("canonical-request")
            try:
                self.assertEqual(audit.current_request_id(), "canonical-request")
            finally:
                audit.reset_request_id(canonical_token)
            self.assertEqual(audit.current_request_id(), "legacy-request")
        finally:
            audit.reset_request_id(old_token)
        self.assertIsNone(audit.current_request_id())

    def test_import_orders_do_not_duplicate_the_shared_audit_handler(self):
        orders = {
            "audit_first": "import app.telemetry.audit as audit; import app.telemetry.http; import app.telemetry.runtime_status; print(len(audit._logger.handlers))",
            "runtime_first": "import app.telemetry.runtime_status; import app.telemetry.http; import app.telemetry.audit as audit; print(len(audit._logger.handlers))",
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

    def test_runtime_state_tracks_start_and_finish(self):
        principal = Principal("tenant-test", "user-test")
        with patch.object(runtime_status, "_users", {}):
            runtime_status.begin_agent_run(principal, "session-1", "  inspect   chamber  ", "demo")
            self.assertEqual(runtime_status.runtime_users()[0]["active_runs"], 1)
            runtime_status.finish_agent_run(principal, "success", "run-1")
            row = runtime_status.runtime_users()[0]
        self.assertEqual((row["active_runs"], row["status"], row["last_run_id"]), (0, "idle", "run-1"))

    def test_http_middleware_resets_request_id_for_success_error_and_cancellation(self):
        async def invoke(app, events):
            messages = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                messages.append(message)

            outer_token = audit.set_request_id("outer-request")
            try:
                with (
                    patch.object(observability, "get_settings", return_value=SimpleNamespace(enterprise_default_tenant_id="default", enterprise_default_user_id="user")),
                    patch.object(observability, "emit") as emit,
                ):
                    try:
                        await observability.RequestAuditMiddleware(app)(
                            {"type": "http", "path": "/api/test", "method": "GET", "headers": []}, receive, send
                        )
                    finally:
                        events[:] = [call.args[0] for call in emit.call_args_list]
                        self.assertEqual(audit.current_request_id(), "outer-request")
            finally:
                audit.reset_request_id(outer_token)
            self.assertIsNone(audit.current_request_id())
            return messages

        async def success(scope, receive, send):
            self.assertTrue(audit.current_request_id().startswith("req-"))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        events = []
        messages = asyncio.run(invoke(success, events))
        self.assertEqual(messages[0]["headers"][-1][0], b"x-request-id")
        self.assertEqual(events, ["api_request_started", "api_request_finished"])

        async def failing(scope, receive, send):
            self.assertTrue(audit.current_request_id().startswith("req-"))
            raise RuntimeError("expected")

        events = []
        messages = asyncio.run(invoke(failing, events))
        self.assertEqual(messages[0]["status"], 500)
        self.assertEqual(events, ["api_request_started", "api_exception", "api_request_finished"])

        async def cancelled(scope, receive, send):
            self.assertTrue(audit.current_request_id().startswith("req-"))
            raise asyncio.CancelledError()

        events = []
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(invoke(cancelled, events))
        self.assertEqual(events, ["api_request_started"])


if __name__ == "__main__":
    unittest.main()
