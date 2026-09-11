from __future__ import annotations

import asyncio
import json
import os
import unittest
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from tests.system.support import isolated_system_environment

isolated_system_environment()

from fastapi.testclient import TestClient

from app.audit import sanitize
from app import agent as agent_module
from app.config import ModelConnection, get_settings
from app.persistence.database import db_session
from app.main import app
from app.model_compatibility import ModelCompatibilityError
from app.model_registry import MODEL_CAPABILITY_DEFAULTS
from app.manufacturing.seed import seed_reference_data

class ModelGovernanceSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_reference_data()

    def setUp(self):
        """Arrange the disposable catalog baseline required by these contracts.

        The reference database may legitimately advertise capabilities learned
        from an administrator-authorized compatibility probe.  System tests
        exercise unsupported-thinking behavior, so they must establish that
        precondition in their isolated snapshot rather than infer it from the
        mutable reference catalog.
        """
        capabilities = json.dumps(MODEL_CAPABILITY_DEFAULTS, separators=(",", ":"))
        with db_session() as connection:
            connection.execute(
                "UPDATE agent.model_catalog SET status = 'retired' "
                "WHERE model_id NOT IN ('deepseekv4-flash', 'deepseekv4-pro')"
            )
            updated = connection.execute(
                """UPDATE agent.model_catalog
                   SET status = 'published', capabilities_json = ?,
                       compatibility_json = '{}', compatibility_checked_at = NULL
                   WHERE model_id IN ('deepseekv4-flash', 'deepseekv4-pro')""",
                (capabilities,),
            ).rowcount
            self.assertEqual(updated, 2, "isolated fixture must contain both default catalog models")
            connection.execute("DELETE FROM agent.user_model_preferences")
            connection.commit()

    def test_model_can_only_be_selected_from_published_catalog(self):
        with TestClient(app) as client:
            initial = client.get("/api/settings/model")
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.json()["allowed_models"], ["deepseekv4-flash", "deepseekv4-pro"])
            self.assertEqual(len(initial.json()["model_options"]), 2)
            self.assertEqual(initial.json()["credential_scope"], "server_managed")
            self.assertIn("health", initial.json())
            self.assertIn("status", initial.json()["health"])
            self.assertIn("consecutive_failures", initial.json()["health"])
            self.assertTrue(all("health" in item for item in initial.json()["model_options"]))
            self.assertTrue(all("status" in item["health"] for item in initial.json()["model_options"]))
            self.assertTrue(all("consecutive_failures" in item["health"] for item in initial.json()["model_options"]))
            self.assertNotIn("api_key_masked", initial.json())
            self.assertNotIn("api_key_source", initial.json())
            self.assertEqual(initial.json()["capabilities"], {"streaming": True, "tool_calls": True, "thinking": False, "native_multimodal": False})
            self.assertEqual(initial.json()["model_options"][0]["capabilities"]["thinking"], False)
            response = client.post("/api/settings/model", json={"model": "deepseekv4-pro"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["model"], "deepseekv4-pro")
            self.assertEqual(response.json()["provider_model"], "deepseek-v4-pro")
            rejected = client.post("/api/settings/model", json={
                "model": "deepseekv4-pro",
                "api_key": "user-supplied-key-must-be-rejected",
            })
            self.assertEqual(rejected.status_code, 422, rejected.text)
            self.assertNotIn("user-supplied-key-must-be-rejected", rejected.text)
            client.post("/api/settings/model", json={"model": "deepseekv4-flash"})

    def test_admin_can_publish_model_and_user_selection_is_scoped(self):
        model_id = "enterprise-test-model"
        admin_token = "enterprise-admin-token"
        with db_session() as connection:
            connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (model_id,))
            connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (model_id,))
            connection.commit()
        try:
            with patch.dict(os.environ, {
                "FAB_ADMIN_API_TOKEN": admin_token,
                "DEEPSEEK_API_KEY": "server-managed-test-key",
            }), patch("app.main.check_model_compatibility", new=AsyncMock(return_value={"status": "passed", "checked_at": "2026-08-11T00:00:00+00:00", "checks": []})), TestClient(app) as client:
                self.assertEqual(client.get("/api/admin/models").status_code, 401)
                admin_headers = {"Authorization": f"Bearer {admin_token}"}
                published = client.post(
                    "/api/admin/models",
                    headers=admin_headers,
                    json={
                        "model_id": model_id,
                        "display_name": "Enterprise Test Model",
                        "provider": "deepseek",
                        "provider_model": "enterprise-test-v1",
                        "base_url": "https://models.example.test/v1",
                        "capabilities": {"streaming": True, "tool_calls": True, "thinking": True, "native_multimodal": True},
                    },
                )
                self.assertEqual(published.status_code, 201, published.text)
                self.assertEqual(published.json()["status"], "published")
                self.assertTrue(published.json()["capabilities"]["thinking"])
                self.assertTrue(published.json()["capabilities"]["native_multimodal"])
                invalid = client.post(
                    "/api/admin/models",
                    headers=admin_headers,
                    json={
                        "model_id": "invalid-blank-name",
                        "display_name": "  ",
                        "provider": "openai-compatible",
                        "provider_model": "enterprise-test-v1",
                        "base_url": "https://models.example.test/v1",
                    },
                )
                self.assertEqual(invalid.status_code, 400, invalid.text)

                user_a = {"X-Tenant-ID": "model-fab", "X-User-ID": "user-a"}
                user_b = {"X-Tenant-ID": "model-fab", "X-User-ID": "user-b"}
                catalog = client.get("/api/settings/model", headers=user_a)
                self.assertIn(model_id, catalog.json()["allowed_models"])
                self.assertTrue(next(item for item in catalog.json()["model_options"] if item["model_id"] == model_id)["capabilities"]["thinking"])
                selected = client.post(
                    "/api/settings/model",
                    headers=user_a,
                    json={"model": model_id},
                )
                self.assertEqual(selected.status_code, 200, selected.text)
                self.assertEqual(selected.json()["model"], model_id)
                self.assertEqual(selected.json()["credential_scope"], "server_managed")
                self.assertNotEqual(client.get("/api/settings/model", headers=user_b).json()["model"], model_id)

                captured = {}

                async def fake_model_stream(client_session, endpoint, headers, request_payload, progress, stream_state):
                    captured.update({"endpoint": endpoint, "headers": headers, "payload": request_payload})
                    return ({"role": "assistant", "content": "模型作用域验证完成"}, {"total_tokens": 3}, "response-model-scope")

                with patch("app.agent._stream_completion", new=fake_model_stream):
                    chat_response = client.post("/api/chat", headers=user_a, json={"message": "查看工厂总览", "thinking": True})
                self.assertEqual(chat_response.status_code, 200, chat_response.text)
                self.assertEqual(captured["payload"]["model"], "enterprise-test-v1")
                self.assertEqual(captured["payload"]["reasoning_effort"], "high")
                self.assertEqual(captured["payload"]["thinking"], {"type": "enabled"})
                self.assertNotIn("tool_choice", captured["payload"])
                self.assertEqual(captured["endpoint"], "https://models.example.test/v1/chat/completions")
                self.assertEqual(captured["headers"]["Authorization"], "Bearer server-managed-test-key")
                expected_policy = {"requested": True, "context_effective": False, "answer_effective": True}
                self.assertEqual(chat_response.json()["thinking_policy"], expected_policy)
                session_id = chat_response.json()["session_id"]
                restored = client.get(f"/api/sessions/{session_id}", headers=user_a)
                self.assertEqual(restored.status_code, 200, restored.text)
                self.assertEqual(restored.json()["messages"][-1]["metadata"]["thinking_policy"], expected_policy)
                client.delete(f"/api/sessions/{session_id}/permanent", headers=user_a)

                client.post("/api/settings/model", headers=user_a, json={"model": "deepseekv4-flash"})
                retired = client.patch(
                    f"/api/admin/models/{model_id}",
                    headers=admin_headers,
                    json={"status": "retired"},
                )
                self.assertEqual(retired.status_code, 200, retired.text)
                self.assertNotIn(model_id, client.get("/api/settings/model", headers=user_a).json()["allowed_models"])
        finally:
            with db_session() as connection:
                connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (model_id,))
                connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (model_id,))
                connection.commit()

    def test_invalid_capabilities_and_unsupported_thinking_have_no_writes(self):
        admin_token = "capability-admin-token"
        with patch.dict(os.environ, {"FAB_ADMIN_API_TOKEN": admin_token}), TestClient(app) as client:
            headers = {"Authorization": f"Bearer {admin_token}"}
            invalid = client.post("/api/admin/models", headers=headers, json={
                "model_id": "invalid-capability", "display_name": "Invalid Capability",
                "provider": "deepseek", "provider_model": "invalid-capability",
                "base_url": "https://models.example.test", "capabilities": {"thinking": "yes"},
            })
            self.assertEqual(invalid.status_code, 422, invalid.text)
            unknown = client.post("/api/admin/models", headers=headers, json={
                "model_id": "unknown-capability", "display_name": "Unknown Capability",
                "provider": "deepseek", "provider_model": "unknown-capability",
                "base_url": "https://models.example.test", "capabilities": {"unknown": True},
            })
            self.assertEqual(unknown.status_code, 422, unknown.text)
            with db_session() as connection:
                before = connection.execute("SELECT COUNT(*) FROM agent.chat_sessions").fetchone()[0]
                messages_before = connection.execute("SELECT COUNT(*) FROM agent.chat_messages").fetchone()[0]
                runs_before = connection.execute("SELECT COUNT(*) FROM agent.agent_runs").fetchone()[0]
            for endpoint in ("/api/chat", "/api/chat/stream"):
                response = client.post(endpoint, json={"message": "请求推理模式", "thinking": True})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["error_code"], "MODEL_CAPABILITY_UNSUPPORTED")
            with db_session() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent.chat_sessions").fetchone()[0], before)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent.chat_messages").fetchone()[0], messages_before)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent.agent_runs").fetchone()[0], runs_before)
            invalid_thinking = client.post("/api/chat", json={"message": "错误推理字段", "thinking": "false"})
            self.assertEqual(invalid_thinking.status_code, 422, invalid_thinking.text)

    def test_admin_declaration_paths_never_probe_and_explicit_check_is_the_only_probe(self):
        model_id, token = "model-016-governance", "model-016-admin-token"
        with db_session() as connection:
            connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (model_id,))
            connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (model_id,))
            connection.commit()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with patch.dict(os.environ, {"FAB_ADMIN_API_TOKEN": token}), patch(
                "app.main.check_model_compatibility", new=AsyncMock(side_effect=AssertionError("declaration must not probe"))
            ) as checker, TestClient(app) as client:
                payload = {"model_id": model_id, "display_name": "Model 016 Governance", "provider": "deepseek", "provider_model": "model-016", "base_url": "https://models.example.test/v1", "capabilities": {"streaming": True, "tool_calls": True, "thinking": False, "native_multimodal": False}}
                published = client.post("/api/admin/models", headers=headers, json=payload)
                self.assertEqual(published.status_code, 201, published.text)
                self.assertEqual(published.json()["compatibility"]["status"], "unverified")
                self.assertEqual(client.patch(f"/api/admin/models/{model_id}", headers=headers, json={"status": "retired"}).status_code, 200)
                self.assertEqual(client.patch(f"/api/admin/models/{model_id}", headers=headers, json={"status": "published"}).status_code, 200)
                changed = client.patch(f"/api/admin/models/{model_id}/capabilities", headers=headers, json={"streaming": True, "tool_calls": True, "thinking": True, "native_multimodal": False})
                self.assertEqual(changed.status_code, 200, changed.text)
                self.assertEqual(changed.json()["status"], "published")
                self.assertEqual(changed.json()["compatibility"]["status"], "unverified")
                self.assertEqual(checker.await_count, 0)
        finally:
            with db_session() as connection:
                connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (model_id,))
                connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (model_id,))
                connection.commit()

    def test_explicit_compatibility_failure_persists_without_changing_model_state(self):
        model_id, token = "model-016-failure", "model-016-failure-token"
        with db_session() as connection:
            connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (model_id,))
            connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (model_id,))
            connection.commit()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            error = ModelCompatibilityError("safe failure", True, "network")
            with patch.dict(os.environ, {"FAB_ADMIN_API_TOKEN": token}), patch(
                "app.main.check_model_compatibility", new=AsyncMock(side_effect=error)
            ), TestClient(app) as client:
                payload = {"model_id": model_id, "display_name": "Model 016 Failure", "provider": "openai-compatible", "provider_model": "model-016", "base_url": "https://models.example.test/v1", "capabilities": {"streaming": True, "tool_calls": True, "thinking": True, "native_multimodal": False}}
                self.assertEqual(client.post("/api/admin/models", headers=headers, json=payload).status_code, 201)
                before = next(item for item in client.get("/api/admin/models", headers=headers).json() if item["model_id"] == model_id)["health"]
                response = client.post(f"/api/admin/models/{model_id}/compatibility-check", headers=headers)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["error_code"], "MODEL_COMPATIBILITY_FAILED")
                model = next(item for item in client.get("/api/admin/models", headers=headers).json() if item["model_id"] == model_id)
                self.assertEqual(model["status"], "published")
                self.assertTrue(model["capabilities"]["thinking"])
                self.assertEqual(model["compatibility"]["status"], "failed")
                self.assertEqual(model["health"], before)
                self.assertNotIn("test-key", str(model["compatibility"]))
        finally:
            with db_session() as connection:
                connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (model_id,))
                connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (model_id,))
                connection.commit()

    def test_explicit_compatibility_success_persists_without_changing_model_state(self):
        model_id, token = "model-018-success", "model-018-success-token"
        with db_session() as connection:
            connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (model_id,))
            connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (model_id,))
            connection.commit()
        headers = {"Authorization": f"Bearer {token}"}
        report = {
            "status": "passed", "checked_at": "2026-08-12T00:00:00.000+00:00", "duration_ms": 12.3,
            "checks": [{"name": "structured_context", "status": "passed"}, {"name": "limits", "status": "passed"}],
        }
        try:
            with patch.dict(os.environ, {"FAB_ADMIN_API_TOKEN": token}), patch(
                "app.main.check_model_compatibility", new=AsyncMock(return_value=report)
            ), TestClient(app) as client:
                payload = {"model_id": model_id, "display_name": "Model 018 Success", "provider": "deepseek", "provider_model": "model-018", "base_url": "https://models.example.test/v1", "capabilities": {"streaming": True, "tool_calls": True, "thinking": True, "native_multimodal": False}}
                self.assertEqual(client.post("/api/admin/models", headers=headers, json=payload).status_code, 201)
                before = next(item for item in client.get("/api/admin/models", headers=headers).json() if item["model_id"] == model_id)
                response = client.post(f"/api/admin/models/{model_id}/compatibility-check", headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                model = next(item for item in client.get("/api/admin/models", headers=headers).json() if item["model_id"] == model_id)
                self.assertEqual(model["status"], before["status"])
                self.assertEqual(model["capabilities"], before["capabilities"])
                self.assertEqual(model["health"], before["health"])
                self.assertEqual(model["compatibility"], report)
        finally:
            with db_session() as connection:
                connection.execute("DELETE FROM agent.user_model_preferences WHERE model_id = ?", (model_id,))
                connection.execute("DELETE FROM agent.model_catalog WHERE model_id = ?", (model_id,))
                connection.commit()

    def test_unknown_model_is_rejected(self):
        with TestClient(app) as client:
            response = client.post("/api/settings/model", json={"model": "unknown-model"})
            self.assertEqual(response.status_code, 400)

    def test_full_logging_still_redacts_credentials(self):
        payload = sanitize({
            "FAB_MODEL_API_KEY": "generic-secret-key",
            "DEEPSEEK_API_KEY": "secret-key",
            "headers": {"Authorization": "Bearer secret-token"},
            "input_tokens": 42,
        })
        self.assertEqual(payload["FAB_MODEL_API_KEY"], "<redacted>")
        self.assertEqual(payload["DEEPSEEK_API_KEY"], "<redacted>")
        self.assertEqual(payload["headers"]["Authorization"], "<redacted>")
        self.assertEqual(payload["input_tokens"], 42)

    def test_model_retries_transient_500_before_first_answer_token(self):
        attempts = 0
        progress_events = []
        request = httpx.Request("POST", "https://example.test/chat/completions")
        transient_error = httpx.HTTPStatusError(
            "temporary failure",
            request=request,
            response=httpx.Response(500, request=request),
        )

        async def fake_stream(*args):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise transient_error
            return ({"role": "assistant", "content": "OK"}, {"total_tokens": 3}, "response-test")

        async def progress(event):
            progress_events.append(event)

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
            api_timeout_seconds=5,
            model_max_retries=2,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=fake_stream),
            patch("app.agent.asyncio.sleep", new=AsyncMock()),
        ):
            result = asyncio.run(agent_module._run_agent_impl("查看工厂总览", [], "run-retry-test", progress))
        self.assertEqual(result["answer"], "OK")
        self.assertEqual(attempts, 2)
        self.assertTrue(any(item.get("stage") == "retrying" for item in progress_events))

    def test_model_does_not_retry_after_answer_output_starts(self):
        attempts = 0
        request = httpx.Request("POST", "https://example.test/chat/completions")
        stream_error = httpx.HTTPStatusError(
            "stream interrupted",
            request=request,
            response=httpx.Response(500, request=request),
        )

        async def failing_stream(*args):
            nonlocal attempts
            attempts += 1
            args[-1]["answer_emitted"] = True
            raise stream_error

        settings = SimpleNamespace(
            model_connection=SimpleNamespace(provider="test", api_key="test-key", base_url="https://example.test", model="test-model"),
            api_timeout_seconds=5,
            model_max_retries=2,
            model_retry_base_seconds=0.05,
        )
        with (
            patch("app.agent.get_settings", return_value=settings),
            patch("app.agent._stream_completion", new=failing_stream),
            patch("app.agent.asyncio.sleep", new=AsyncMock()),
        ):
            with self.assertRaises(httpx.HTTPStatusError):
                asyncio.run(agent_module._run_agent_impl("查看工厂总览", [], "run-no-retry-test"))
        self.assertEqual(attempts, 1)

    def _health_settings(self, *, retries: int = 0):
        base = get_settings()
        return replace(
            base,
            model_connection=ModelConnection("test", "test-key", "https://example.test", "test-model"),
            model_max_retries=retries,
        )

    @contextmanager
    def _health_patches(self, settings, claim):
        with ExitStack() as stack:
            stack.enter_context(patch("app.agent.get_settings", return_value=settings))
            stack.enter_context(patch("app.agent.public_user_model_config", return_value={"model": "test-model"}))
            stack.enter_context(patch("app.agent.get_model_health", return_value={"status": "unknown"}))
            stack.enter_context(patch("app.agent.claim_model_call", side_effect=claim))
            yield

    def test_open_circuit_skips_model_call_and_uses_local_rules(self):
        settings = self._health_settings()
        calls = 0

        async def stream(*args):
            nonlocal calls
            calls += 1
            raise AssertionError("open circuit must not call upstream")

        with self._health_patches(settings, [(False, {"status": "open"}, None)]), patch("app.agent._stream_completion", new=stream):
            result = asyncio.run(agent_module._run_agent_impl("查看工厂总览", [], "run-open-circuit"))
        self.assertEqual(calls, 0)
        self.assertEqual(result["model"], "local-rules")
        self.assertEqual(result["model_health"]["fallback_reason"], "circuit_open")

    def test_final_retryable_failure_records_once_and_falls_back(self):
        settings = self._health_settings(retries=1)
        request = httpx.Request("POST", "https://example.test/chat/completions")
        error = httpx.HTTPStatusError("down", request=request, response=httpx.Response(500, request=request))

        async def stream(*args):
            raise error

        with self._health_patches(settings, [(True, {"status": "healthy"}, None)]), patch("app.agent._stream_completion", new=stream), patch("app.agent.record_model_failure", return_value=({"status": "degraded"}, None)) as failure, patch("app.agent.asyncio.sleep", new=AsyncMock()):
            result = asyncio.run(agent_module._run_agent_impl("查看工厂总览", [], "run-final-failure"))
        self.assertEqual(failure.call_count, 1)
        self.assertEqual(result["model"], "local-rules")
        self.assertEqual(result["model_health"]["fallback_reason"], "upstream_unavailable")

    def test_partial_response_failure_records_once_and_does_not_fallback(self):
        settings = self._health_settings()
        events: list[tuple[str, dict]] = []
        request = httpx.Request("POST", "https://example.test/chat/completions")
        error = httpx.HTTPStatusError("down", request=request, response=httpx.Response(500, request=request))

        async def stream(*args):
            args[-1]["answer_emitted"] = True
            args[-1]["content_chars"] = 17
            raise error

        def capture(event_type: str, run_id: str, **fields) -> None:
            events.append((event_type, fields))

        with self._health_patches(settings, [(True, {"status": "healthy"}, None)]), patch("app.agent._stream_completion", new=stream), patch("app.agent.record_model_failure", return_value=({"status": "degraded"}, None)) as failure, patch("app.agent._offline_answer") as offline, patch("app.agent.emit", new=capture):
            with self.assertRaises(httpx.HTTPStatusError):
                asyncio.run(agent_module._run_agent_impl("查看工厂总览", [], "run-partial-failure"))
        self.assertEqual(failure.call_count, 1)
        offline.assert_not_called()
        failure_event = next(fields for event, fields in events if event == "model_call_finished")
        self.assertEqual(failure_event["content_length"], 17)

    def test_non_retryable_4xx_does_not_change_health_or_fallback(self):
        settings = self._health_settings()
        request = httpx.Request("POST", "https://example.test/chat/completions")
        error = httpx.HTTPStatusError("bad request", request=request, response=httpx.Response(400, request=request))

        async def stream(*args):
            raise error

        with self._health_patches(settings, [(True, {"status": "healthy"}, None)]), patch("app.agent._stream_completion", new=stream), patch("app.agent.record_model_failure") as failure, patch("app.agent._offline_answer") as offline:
            with self.assertRaises(httpx.HTTPStatusError):
                asyncio.run(agent_module._run_agent_impl("查看工厂总览", [], "run-4xx"))
        failure.assert_not_called()
        offline.assert_not_called()

    def test_successful_call_records_health_success(self):
        settings = self._health_settings()

        async def stream(*args):
            return {"role": "assistant", "content": "OK"}, {"total_tokens": 1}, "response"

        with self._health_patches(settings, [(True, {"status": "healthy"}, None)]), patch("app.agent._stream_completion", new=stream), patch("app.agent.record_model_success", return_value=({"status": "healthy"}, None)) as success:
            result = asyncio.run(agent_module._run_agent_impl("查看工厂总览", [], "run-health-success"))
        self.assertEqual(result["answer"], "OK")
        self.assertEqual(success.call_count, 1)

    def test_half_open_recovery_trial_has_no_transport_retry(self):
        settings = self._health_settings(retries=2)
        attempts = 0
        request = httpx.Request("POST", "https://example.test/chat/completions")
        error = httpx.HTTPStatusError("down", request=request, response=httpx.Response(500, request=request))

        async def stream(*args):
            nonlocal attempts
            attempts += 1
            raise error

        with self._health_patches(settings, [(True, {"status": "half_open"}, "recovery_started")]), patch("app.agent._stream_completion", new=stream), patch("app.agent.record_model_failure", return_value=({"status": "open"}, "opened")):
            result = asyncio.run(agent_module._run_agent_impl("查看工厂总览", [], "run-half-open-once"))
        self.assertEqual(attempts, 1)
        self.assertEqual(result["model"], "local-rules")

    def test_context_availability_failure_opens_circuit_before_main_completion(self):
        settings = self._health_settings()
        calls = 0
        request = httpx.Request("POST", "https://example.test/chat/completions")
        error = httpx.HTTPStatusError("down", request=request, response=httpx.Response(500, request=request))

        async def stream(*args):
            nonlocal calls
            calls += 1
            raise error

        history = [{"role": "user", "content": "昨天 CMP-03 的异常如何处理？"}]
        claims = [
            (True, {"status": "healthy"}, None),
            (False, {"status": "open"}, None),
        ]
        with self._health_patches(settings, claims), patch("app.agent._stream_completion", new=stream), patch("app.agent.record_model_failure", return_value=({"status": "open"}, "opened")) as failure:
            result = asyncio.run(agent_module._run_agent_impl("查看 CMP-03 当前健康", history, "run-context-opens-circuit"))
        self.assertEqual(calls, 1)
        self.assertEqual(failure.call_count, 1)
        self.assertEqual(result["model"], "local-rules")
        self.assertEqual(result["model_health"]["fallback_reason"], "circuit_open")

if __name__ == "__main__":
    unittest.main()
